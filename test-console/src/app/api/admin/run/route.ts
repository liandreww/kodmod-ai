import { NextRequest, NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { projectDir } from "@/lib/paths";
import { publish } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Only these scripts can be launched -- no arbitrary command execution. */
const SCRIPTS: Record<string, { args: string[]; label: string; destructive: boolean }> = {
  init_test_db: {
    args: ["-m", "scripts.init_test_db"],
    label: "Create schema and seed the test database",
    destructive: true,
  },
  create_test_db: {
    args: ["-m", "scripts.create_test_db"],
    label: "Create schema only (ORM create_all + curriculum_chunks DDL)",
    destructive: true,
  },
  seed_curriculum: {
    args: ["-m", "scripts.seed_curriculum"],
    label: "Seed subjects, concepts and lessons (idempotent)",
    destructive: false,
  },
  ingest_documents: {
    args: ["-m", "scripts.ingest_documents", "--path", "data/curriculum"],
    label: "Chunk, embed and store data/curriculum into curriculum_chunks",
    destructive: false,
  },
};

export async function GET() {
  return NextResponse.json({
    cwd: projectDir(),
    python: process.env.KODMOD_PYTHON || "python",
    scripts: Object.entries(SCRIPTS).map(([name, s]) => ({
      name,
      label: s.label,
      destructive: s.destructive,
      command: `python ${s.args.join(" ")}`,
    })),
  });
}

export async function POST(req: NextRequest) {
  const { script } = await req.json();
  const entry = SCRIPTS[String(script)];
  if (!entry) return NextResponse.json({ error: `unknown script: ${script}` }, { status: 400 });

  const python = process.env.KODMOD_PYTHON || "python";
  const cwd = projectDir();
  publish("proc", `run: ${python} ${entry.args.join(" ")}`, { level: "warn", detail: { cwd } });

  return new Promise<NextResponse>((resolve) => {
    const child = spawn(python, entry.args, { cwd, windowsHide: true, env: { ...process.env } });
    const lines: string[] = [];
    const started = Date.now();

    const consume = (stream: NodeJS.ReadableStream | null, level: "info" | "error") => {
      let buf = "";
      stream?.on("data", (chunk: Buffer) => {
        buf += chunk.toString("utf8");
        const parts = buf.split(/\r?\n/);
        buf = parts.pop() ?? "";
        for (const line of parts) {
          if (!line.trim()) continue;
          lines.push(line);
          publish("proc", line.slice(0, 400), { level: level === "error" && /error|traceback/i.test(line) ? "error" : "info" });
        }
      });
    };

    consume(child.stdout, "info");
    consume(child.stderr, "error");

    child.on("error", (err) => {
      publish("proc", `spawn failed: ${err.message}`, { level: "error" });
      resolve(NextResponse.json({ error: err.message, cwd, python }, { status: 500 }));
    });

    child.on("close", (code) => {
      const durationMs = Date.now() - started;
      publish("proc", `${script} exited with ${code}`, {
        level: code === 0 ? "info" : "error",
        durationMs,
      });
      resolve(
        NextResponse.json({
          ok: code === 0,
          exitCode: code,
          durationMs,
          output: lines.join("\n"),
          cwd,
          command: `${python} ${entry.args.join(" ")}`,
        }),
      );
    });
  });
}
