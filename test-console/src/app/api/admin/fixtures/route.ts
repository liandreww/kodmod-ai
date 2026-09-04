import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { query } from "@/lib/pg";
import { clientFor, scanKeys } from "@/lib/redis";
import { publish } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Fixed UUIDs from kodmod-ai/tests/conftest.py:57-61. No seed script creates them. */
const FIXTURES = {
  students: [
    { id: "11111111-1111-1111-1111-111111111111", full_name: "Siswa Uji (blind)", email: "blind@kodmod.test", grade_level: "6", accessibility_profile: "blind", preferred_language: "id" },
    { id: "11111111-1111-1111-1111-111111111112", full_name: "Siswa Uji (low vision)", email: "lowvision@kodmod.test", grade_level: "6", accessibility_profile: "low_vision", preferred_language: "id" },
    { id: "11111111-1111-1111-1111-111111111113", full_name: "Siswa Uji (strong)", email: "strong@kodmod.test", grade_level: "6", accessibility_profile: "blind", preferred_language: "id" },
  ],
  teachers: [
    { id: "22222222-2222-2222-2222-222222222221", full_name: "Guru A", email: "guru.a@kodmod.test", subject_specialty: "Matematika" },
  ],
  classrooms: [
    { id: "33333333-3333-3333-3333-333333333331", name: "Kelas A", grade_level: "6", teacher_id: "22222222-2222-2222-2222-222222222221" },
  ],
};

/** Mastery presets from kodmod-ai/docs/testplan/test-data.md, keyed by concept slug. */
const MASTERY_PRESETS: Record<string, Record<string, number>> = {
  weak: { pecahan: 0.25, "persamaan-linear": 0.3, "bangun-datar": 0.35 },
  mixed: { pecahan: 0.55, fotosintesis: 0.8, "tata-surya": 0.4 },
  strong: { pecahan: 0.9, fotosintesis: 0.88, "kalimat-efektif": 0.85 },
};

/** Child-first so foreign keys never block the truncate. */
const ACTIVITY_TABLES = [
  "quiz_attempts",
  "quiz_questions",
  "quiz_sessions",
  "interaction_logs",
  "learning_sessions",
  "mastery_scores",
  "misconceptions",
  "analytics_reports",
  "recommendations",
];

const CURRICULUM_TABLES = ["exercises", "lessons", "concepts", "subjects", "curriculum_chunks"];
const IDENTITY_TABLES = ["classroom_enrollment", "classrooms", "students", "teachers"];

export async function GET() {
  const profile = await activeProfile();
  const present = await query(
    profile,
    `select
       (select count(*)::int from students  where id = any($1::uuid[])) as students,
       (select count(*)::int from teachers  where id = any($2::uuid[])) as teachers,
       (select count(*)::int from classrooms where id = any($3::uuid[])) as classrooms`,
    [
      FIXTURES.students.map((s) => s.id),
      FIXTURES.teachers.map((t) => t.id),
      FIXTURES.classrooms.map((c) => c.id),
    ],
    { quiet: true },
  );

  const concepts = await query(profile, "select id, slug, name from concepts order by slug", [], { quiet: true });

  return NextResponse.json({
    fixtures: FIXTURES,
    presets: Object.keys(MASTERY_PRESETS),
    present: present.rows[0],
    concepts: concepts.rows,
    tables: { activity: ACTIVITY_TABLES, curriculum: CURRICULUM_TABLES, identity: IDENTITY_TABLES },
  });
}

export async function POST(req: NextRequest) {
  const profile = await activeProfile();
  const body = await req.json();
  const action = String(body.action ?? "");

  try {
    switch (action) {
      case "createFixtures": {
        for (const s of FIXTURES.students) {
          await query(
            profile,
            `insert into students (id, full_name, email, grade_level, accessibility_profile, preferred_language, voice_settings, created_at, updated_at)
             values ($1, $2, $3, $4, $5, $6, '{}'::json, now(), now())
             on conflict (id) do update set full_name = excluded.full_name, updated_at = now()`,
            [s.id, s.full_name, s.email, s.grade_level, s.accessibility_profile, s.preferred_language],
            { label: `fixture student ${s.full_name}` },
          );
        }
        for (const t of FIXTURES.teachers) {
          await query(
            profile,
            `insert into teachers (id, full_name, email, subject_specialty, created_at)
             values ($1, $2, $3, $4, now())
             on conflict (id) do update set full_name = excluded.full_name`,
            [t.id, t.full_name, t.email, t.subject_specialty],
            { label: `fixture teacher ${t.full_name}` },
          );
        }
        for (const c of FIXTURES.classrooms) {
          await query(
            profile,
            `insert into classrooms (id, name, teacher_id, grade_level, created_at)
             values ($1, $2, $3, $4, now())
             on conflict (id) do update set name = excluded.name, teacher_id = excluded.teacher_id`,
            [c.id, c.name, c.teacher_id, c.grade_level],
            { label: `fixture classroom ${c.name}` },
          );
          for (const s of FIXTURES.students) {
            await query(
              profile,
              `insert into classroom_enrollment (classroom_id, student_id, enrolled_at)
               values ($1, $2, now()) on conflict do nothing`,
              [c.id, s.id],
              { label: "fixture enrollment" },
            );
          }
        }
        publish("system", "test fixtures created (students, teacher, classroom, enrollment)");
        return NextResponse.json({ ok: true });
      }

      case "applyMastery": {
        const studentId = String(body.studentId ?? "");
        const preset = MASTERY_PRESETS[String(body.preset ?? "")];
        if (!studentId || !preset) {
          return NextResponse.json({ error: "studentId and a known preset are required" }, { status: 400 });
        }
        const slugs = Object.keys(preset);
        const concepts = await query(
          profile,
          "select id, slug from concepts where slug = any($1::text[])",
          [slugs],
          { quiet: true },
        );
        const rows = concepts.rows as { id: string; slug: string }[];
        const missing = slugs.filter((s) => !rows.some((r) => r.slug === s));

        for (const row of rows) {
          await query(
            profile,
            `insert into mastery_scores (id, student_id, concept_id, mastery, confidence, n_attempts, last_seen)
             values (gen_random_uuid(), $1, $2, $3, 0.7, 5, now())
             on conflict (student_id, concept_id)
             do update set mastery = excluded.mastery, confidence = excluded.confidence,
                           n_attempts = excluded.n_attempts, last_seen = now()`,
            [studentId, row.id, preset[row.slug]],
            { label: `mastery ${row.slug} = ${preset[row.slug]}` },
          );
        }
        publish("system", `applied mastery preset "${body.preset}" to ${studentId}`, { detail: { missing } });
        return NextResponse.json({ ok: true, applied: rows.length, missingSlugs: missing });
      }

      case "truncate": {
        const scope = String(body.scope ?? "activity");
        let tables: string[];
        if (scope === "activity") tables = ACTIVITY_TABLES;
        else if (scope === "curriculum") tables = CURRICULUM_TABLES;
        else if (scope === "identity") tables = [...ACTIVITY_TABLES, ...IDENTITY_TABLES];
        else tables = [...ACTIVITY_TABLES, ...CURRICULUM_TABLES, ...IDENTITY_TABLES];

        const existing = await query(
          profile,
          `select table_name from information_schema.tables
            where table_schema = 'public' and table_name = any($1::text[])`,
          [tables],
          { quiet: true },
        );
        const names = (existing.rows as { table_name: string }[]).map((r) => `"${r.table_name}"`);
        if (!names.length) return NextResponse.json({ ok: true, truncated: [] });

        await query(profile, `truncate ${names.join(", ")} restart identity cascade`, [], {
          label: `TRUNCATE ${scope}`,
        });
        publish("system", `truncated ${names.length} tables (${scope})`, { level: "warn" });
        return NextResponse.json({ ok: true, truncated: names });
      }

      case "resetChunks": {
        const dim = Math.max(1, Math.min(Number(body.dim ?? 1024), 4096));
        await query(profile, "drop table if exists curriculum_chunks cascade", [], {
          label: "drop curriculum_chunks",
        });
        await query(profile, "create extension if not exists vector", [], { quiet: true });
        await query(profile, "create extension if not exists pgcrypto", [], { quiet: true });
        await query(
          profile,
          `create table curriculum_chunks (
             id                     uuid primary key default gen_random_uuid(),
             content                text not null,
             embedding              vector(${dim}) not null,
             source                 text not null default '',
             language               varchar(8) not null default 'id',
             concept_id             uuid,
             chunk_index            int not null default 0,
             section_title          text,
             accessibility_metadata jsonb not null default '{}'::jsonb,
             created_at             timestamptz not null default now()
           )`,
          [],
          { label: `create curriculum_chunks vector(${dim})` },
        );
        await query(
          profile,
          "create index if not exists idx_cc_embedding_hnsw on curriculum_chunks using hnsw (embedding vector_cosine_ops)",
          [],
          { quiet: true },
        );
        await query(profile, "create index if not exists idx_cc_concept on curriculum_chunks (concept_id)", [], { quiet: true });
        await query(profile, "create index if not exists idx_cc_source on curriculum_chunks (source)", [], { quiet: true });
        publish("system", `curriculum_chunks recreated with vector(${dim})`, { level: "warn" });
        return NextResponse.json({ ok: true, dim });
      }

      case "wipeRedis": {
        const pattern = String(body.pattern ?? "kodmod:*");
        const keys = await scanKeys(profile, pattern, 10_000);
        const n = keys.length ? await clientFor(profile).del(...keys) : 0;
        publish("system", `wiped ${n} Redis keys matching ${pattern}`, { level: "warn" });
        return NextResponse.json({ ok: true, deleted: n });
      }

      case "purgeCheckpoints": {
        const out: Record<string, number> = {};
        for (const t of ["checkpoint_writes", "checkpoint_blobs", "checkpoints"]) {
          const exists = await query(
            profile,
            `select count(*)::int as n from information_schema.tables
              where table_schema = 'public' and table_name = $1`,
            [t],
            { quiet: true },
          );
          if (Number((exists.rows[0] as { n: number }).n) === 0) continue;
          const r = await query(profile, `delete from ${t}`, [], { label: `purge ${t}` });
          out[t] = r.rowCount;
        }
        publish("system", "purged all LangGraph checkpoints", { level: "warn" });
        return NextResponse.json({ ok: true, deleted: out });
      }

      default:
        return NextResponse.json({ error: `unknown action: ${action}` }, { status: 400 });
    }
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 400 });
  }
}
