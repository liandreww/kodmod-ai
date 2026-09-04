import { NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { query } from "@/lib/pg";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Exact row counts for every public table, used by the dashboard and the Effects rail. */
export async function GET() {
  const profile = await activeProfile();

  const tables = await query(
    profile,
    `select table_name from information_schema.tables
      where table_schema = 'public' and table_type = 'BASE TABLE'
      order by table_name`,
    [],
    { quiet: true },
  );

  const names = (tables.rows as { table_name: string }[]).map((r) => r.table_name);
  if (!names.length) return NextResponse.json({ counts: {}, tables: [] });

  const union = names
    .map((n) => `select '${n}'::text as t, count(*)::int as n from "${n}"`)
    .join(" union all ");

  const res = await query(profile, union, [], { label: `count rows in ${names.length} tables` });
  const counts: Record<string, number> = {};
  for (const row of res.rows as { t: string; n: number }[]) counts[row.t] = Number(row.n);

  return NextResponse.json({ counts, tables: names });
}
