import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { query } from "@/lib/pg";
import { decodeBlob, describe } from "@/lib/msgpack";
import { publish } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** The 15 graph nodes, contract-locked in tests/contract/test_graph_wiring.py:19. */
const NODES = [
  "stt", "intent_router", "rag_retrieval", "tutoring", "mini_quiz",
  "problem_generator", "quiz_ask", "scoring", "quiz_analyzer",
  "update_student_model", "analytics", "recommendation",
  "accessibility", "reflection", "tts",
];

/** The graph compiles with interrupt_after=["reflection"] whenever a checkpointer is present. */
const INTERRUPT_AFTER = "reflection";

const MAX_VALUE_CHARS = 24_000;

function cap(value: unknown): unknown {
  try {
    const json = JSON.stringify(value);
    if (json && json.length > MAX_VALUE_CHARS) {
      return { __truncated: true, chars: json.length, summary: describe(value), head: json.slice(0, 2000) };
    }
  } catch {
    return { __unserialisable: true, summary: describe(value) };
  }
  return value;
}

/** Pregel bookkeeping channels that are noise in a state view. */
function isInternalChannel(name: string): boolean {
  return name.startsWith("__") || name.startsWith("branch:") || name.startsWith("start:");
}

/** task_path looks like "~__pregel_pull, intent_router". */
function nodeFromTaskPath(path: string | null): string {
  if (!path) return "";
  const parts = String(path).split(",");
  return parts[parts.length - 1].trim();
}

interface Task {
  taskId: string;
  node: string;
  taskPath: string | null;
  /** Exactly the partial state dict the node returned. */
  output: Record<string, unknown>;
}

async function hasCheckpointTables(profile: Awaited<ReturnType<typeof activeProfile>>) {
  const r = await query(
    profile,
    `select count(*)::int as n from information_schema.tables
      where table_schema = 'public' and table_name in ('checkpoints','checkpoint_blobs','checkpoint_writes')`,
    [],
    { quiet: true },
  );
  return Number((r.rows[0] as { n: number }).n) === 3;
}

export async function GET(req: NextRequest) {
  const profile = await activeProfile();
  const threadId = req.nextUrl.searchParams.get("thread");

  if (!(await hasCheckpointTables(profile))) {
    return NextResponse.json({
      available: false,
      reason:
        "checkpoint tables are missing. The API is running with KODMOD_CHECKPOINTER=memory, " +
        "so no graph state is persisted. Restart it without that variable to record traces.",
      threads: [],
    });
  }

  if (!threadId) {
    const threads = await query(
      profile,
      `select c.thread_id,
              count(*)::int            as steps,
              min(c.checkpoint->>'ts') as first_ts,
              max(c.checkpoint->>'ts') as last_ts
         from checkpoints c
        group by c.thread_id
        order by max(c.checkpoint->>'ts') desc nulls last
        limit 200`,
      [],
      { label: "list checkpoint threads" },
    );
    return NextResponse.json({ available: true, threads: threads.rows });
  }

  const cps = await query(
    profile,
    `select thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
       from checkpoints
      where thread_id = $1
      order by checkpoint_ns, checkpoint_id`,
    [threadId],
    { label: `read checkpoints for thread ${threadId}` },
  );

  const blobRows = await query(
    profile,
    `select checkpoint_ns, channel, version, type, blob
       from checkpoint_blobs
      where thread_id = $1`,
    [threadId],
    { label: `read checkpoint_blobs for thread ${threadId}` },
  );

  // task_path was added in a later schema revision; tolerate its absence.
  let writeRows: Record<string, unknown>[] = [];
  try {
    const res = await query(
      profile,
      `select checkpoint_ns, checkpoint_id, task_id, task_path, idx, channel, type, blob
         from checkpoint_writes
        where thread_id = $1
        order by checkpoint_id, task_id, idx`,
      [threadId],
      { label: `read checkpoint_writes for thread ${threadId}` },
    );
    writeRows = res.rows;
  } catch {
    const res = await query(
      profile,
      `select checkpoint_ns, checkpoint_id, task_id, null::text as task_path, idx, channel, type, blob
         from checkpoint_writes
        where thread_id = $1
        order by checkpoint_id, task_id, idx`,
      [threadId],
      { label: `read checkpoint_writes (no task_path) for thread ${threadId}` },
    );
    writeRows = res.rows;
  }

  // channel + version -> decoded value
  const blobIndex = new Map<string, unknown>();
  for (const row of blobRows.rows as Record<string, unknown>[]) {
    blobIndex.set(`${row.checkpoint_ns}|${row.channel}|${row.version}`, decodeBlob(row.type as string, row.blob as Buffer));
  }

  // checkpoint_id -> tasks that were scheduled from it. Their writes are the
  // output of the node that ran to produce the *next* checkpoint.
  const tasksByCheckpoint = new Map<string, Map<string, Task>>();
  for (const row of writeRows) {
    const cpId = String(row.checkpoint_id);
    const taskId = String(row.task_id);
    if (!tasksByCheckpoint.has(cpId)) tasksByCheckpoint.set(cpId, new Map());
    const bucket = tasksByCheckpoint.get(cpId)!;
    if (!bucket.has(taskId)) {
      bucket.set(taskId, {
        taskId,
        node: nodeFromTaskPath(row.task_path as string | null),
        taskPath: (row.task_path as string) ?? null,
        output: {},
      });
    }
    const channel = String(row.channel);
    if (isInternalChannel(channel)) continue;
    bucket.get(taskId)!.output[channel] = cap(decodeBlob(row.type as string, row.blob as Buffer));
  }

  const steps = (cps.rows as Record<string, unknown>[]).map((row) => {
    const checkpoint = (row.checkpoint ?? {}) as Record<string, unknown>;
    const metadata = (row.metadata ?? {}) as Record<string, unknown>;
    const channelVersions = (checkpoint.channel_versions ?? {}) as Record<string, unknown>;
    const inlineValues = (checkpoint.channel_values ?? {}) as Record<string, unknown>;

    // Simple channels are stored inline in the checkpoint JSONB; containers
    // (messages, retrieved_docs, tutoring_context, ...) live in checkpoint_blobs.
    const state: Record<string, unknown> = {};
    for (const [channel, value] of Object.entries(inlineValues)) {
      if (isInternalChannel(channel)) continue;
      state[channel] = cap(value);
    }
    for (const [channel, version] of Object.entries(channelVersions)) {
      if (isInternalChannel(channel)) continue;
      const value = blobIndex.get(`${row.checkpoint_ns}|${channel}|${version}`);
      if (value !== undefined) state[channel] = cap(value);
    }

    const parentId = row.parent_checkpoint_id ? String(row.parent_checkpoint_id) : null;
    const producedBy = parentId ? Array.from(tasksByCheckpoint.get(parentId)?.values() ?? []) : [];
    const scheduled = Array.from(tasksByCheckpoint.get(String(row.checkpoint_id))?.values() ?? []);

    return {
      checkpointId: row.checkpoint_id,
      parentCheckpointId: parentId,
      ns: row.checkpoint_ns,
      ts: checkpoint.ts ?? null,
      step: metadata.step ?? null,
      source: metadata.source ?? null,
      /** Node(s) whose output produced this checkpoint. */
      nodes: producedBy.map((t) => t.node).filter(Boolean),
      /** Exactly what each of those nodes returned. */
      producedBy,
      /** Tasks scheduled from this checkpoint whose writes are not applied yet. */
      scheduled,
      state,
      metadata,
      versionsSeen: checkpoint.versions_seen ?? {},
    };
  });

  const last = steps[steps.length - 1];
  const interrupted = !!last && last.scheduled.length > 0;
  const pausedAfter = last?.nodes.includes(INTERRUPT_AFTER) ? INTERRUPT_AFTER : null;

  return NextResponse.json({
    available: true,
    threadId,
    steps,
    nodeOrder: NODES,
    interrupted,
    pausedAfter,
    interruptNode: INTERRUPT_AFTER,
    counts: {
      checkpoints: cps.rowCount,
      blobs: blobRows.rowCount,
      writes: writeRows.length,
    },
  });
}

export async function DELETE(req: NextRequest) {
  const profile = await activeProfile();
  const threadId = req.nextUrl.searchParams.get("thread");
  if (!threadId) return NextResponse.json({ error: "thread is required" }, { status: 400 });

  const a = await query(profile, "delete from checkpoint_writes where thread_id = $1", [threadId], {
    label: `purge checkpoint_writes ${threadId}`,
  });
  const b = await query(profile, "delete from checkpoint_blobs where thread_id = $1", [threadId], {
    label: `purge checkpoint_blobs ${threadId}`,
  });
  const c = await query(profile, "delete from checkpoints where thread_id = $1", [threadId], {
    label: `purge checkpoints ${threadId}`,
  });

  publish("system", `purged checkpoint thread ${threadId}`, { level: "warn" });
  return NextResponse.json({ ok: true, writes: a.rowCount, blobs: b.rowCount, checkpoints: c.rowCount });
}
