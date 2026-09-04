import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { presentRows, query } from "@/lib/pg";
import type { Profile } from "@/lib/profiles";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface ColumnMeta {
  column_name: string;
  data_type: string;
  udt_name: string;
  is_nullable: string;
}

/** Only identifiers that exist in information_schema are ever interpolated. */
async function columnsOf(profile: Profile, table: string): Promise<ColumnMeta[]> {
  const res = await query(
    profile,
    `select column_name, data_type, udt_name, is_nullable
       from information_schema.columns
      where table_schema = 'public' and table_name = $1
      order by ordinal_position`,
    [table],
    { quiet: true },
  );
  return res.rows as unknown as ColumnMeta[];
}

async function primaryKeyOf(profile: Profile, table: string): Promise<string[]> {
  const res = await query(
    profile,
    `select kcu.column_name
       from information_schema.table_constraints tc
       join information_schema.key_column_usage kcu
         on kcu.constraint_name = tc.constraint_name and kcu.table_schema = tc.table_schema
      where tc.table_schema = 'public' and tc.table_name = $1 and tc.constraint_type = 'PRIMARY KEY'
      order by kcu.ordinal_position`,
    [table],
    { quiet: true },
  );
  return (res.rows as { column_name: string }[]).map((r) => r.column_name);
}

function q(ident: string): string {
  return `"${ident.replace(/"/g, '""')}"`;
}

/** vector columns are projected as a dimension label so a row does not carry 1024 floats. */
function selectList(cols: ColumnMeta[]): string {
  return cols
    .map((c) => {
      if (c.udt_name === "vector") {
        return `case when ${q(c.column_name)} is null then null
                     else 'vector(' || vector_dims(${q(c.column_name)}) || ')' end as ${q(c.column_name)}`;
      }
      return q(c.column_name);
    })
    .join(", ");
}

export async function GET(req: NextRequest) {
  const profile = await activeProfile();
  const sp = req.nextUrl.searchParams;
  const table = sp.get("table") ?? "";
  const limit = Math.min(Math.max(Number(sp.get("limit") ?? 50), 1), 500);
  const offset = Math.max(Number(sp.get("offset") ?? 0), 0);
  const orderBy = sp.get("orderBy") ?? "";
  const orderDir = sp.get("orderDir") === "asc" ? "asc" : "desc";
  const filterCol = sp.get("filterCol") ?? "";
  const filterVal = sp.get("filterVal") ?? "";

  const cols = await columnsOf(profile, table);
  if (!cols.length) return NextResponse.json({ error: `unknown table: ${table}` }, { status: 400 });
  const names = new Set(cols.map((c) => c.column_name));
  const pk = await primaryKeyOf(profile, table);

  const params: unknown[] = [];
  let where = "";
  if (filterCol && names.has(filterCol) && filterVal !== "") {
    params.push(`%${filterVal}%`);
    where = ` where ${q(filterCol)}::text ilike $${params.length}`;
  }

  let order = "";
  if (orderBy && names.has(orderBy)) {
    order = ` order by ${q(orderBy)} ${orderDir} nulls last`;
  } else {
    const fallback =
      cols.find((c) => /(_at|timestamp|last_seen|detected_at|answered_at|started_at)$/.test(c.column_name))
        ?.column_name ?? pk[0] ?? cols[0].column_name;
    order = ` order by ${q(fallback)} desc nulls last`;
  }

  const sql = `select ${selectList(cols)} from ${q(table)}${where}${order} limit ${limit} offset ${offset}`;
  const rows = await query(profile, sql, params, { label: `browse ${table}` });

  const total = await query(
    profile,
    `select count(*)::int as n from ${q(table)}${where}`,
    params,
    { quiet: true },
  );

  return NextResponse.json({
    table,
    columns: cols,
    primaryKey: pk,
    rows: presentRows(rows.rows),
    total: Number((total.rows[0] as { n: number }).n),
    limit,
    offset,
    sql,
    durationMs: rows.durationMs,
  });
}

export async function POST(req: NextRequest) {
  const profile = await activeProfile();
  const body = await req.json();
  const action = String(body.action ?? "");
  const table = String(body.table ?? "");

  const cols = await columnsOf(profile, table);
  if (!cols.length) return NextResponse.json({ error: `unknown table: ${table}` }, { status: 400 });
  const names = new Set(cols.map((c) => c.column_name));
  const pk = await primaryKeyOf(profile, table);

  try {
    if (action === "insert") {
      const values = body.values as Record<string, unknown>;
      const entries = Object.entries(values).filter(([k, v]) => names.has(k) && v !== undefined && v !== "");
      if (!entries.length) return NextResponse.json({ error: "no values" }, { status: 400 });
      const params = entries.map(([, v]) => coerce(v));
      const sql = `insert into ${q(table)} (${entries.map(([k]) => q(k)).join(", ")})
                   values (${entries.map((_, i) => `$${i + 1}`).join(", ")}) returning *`;
      const res = await query(profile, sql, params, { label: `insert into ${table}` });
      return NextResponse.json({ ok: true, rows: presentRows(res.rows), sql });
    }

    if (action === "update") {
      const values = body.values as Record<string, unknown>;
      const where = body.where as Record<string, unknown>;
      const sets = Object.entries(values).filter(([k]) => names.has(k));
      const conds = Object.entries(where).filter(([k]) => names.has(k));
      if (!sets.length || !conds.length) {
        return NextResponse.json({ error: "update needs values and a where clause" }, { status: 400 });
      }
      const params: unknown[] = [];
      const setSql = sets
        .map(([k, v]) => {
          params.push(coerce(v));
          return `${q(k)} = $${params.length}`;
        })
        .join(", ");
      const whereSql = conds
        .map(([k, v]) => {
          params.push(coerce(v));
          return `${q(k)} = $${params.length}`;
        })
        .join(" and ");
      const sql = `update ${q(table)} set ${setSql} where ${whereSql} returning *`;
      const res = await query(profile, sql, params, { label: `update ${table}` });
      return NextResponse.json({ ok: true, rows: presentRows(res.rows), rowCount: res.rowCount, sql });
    }

    if (action === "delete") {
      const where = body.where as Record<string, unknown>;
      const conds = Object.entries(where).filter(([k]) => names.has(k));
      if (!conds.length) return NextResponse.json({ error: "delete needs a where clause" }, { status: 400 });
      const params: unknown[] = [];
      const whereSql = conds
        .map(([k, v]) => {
          params.push(coerce(v));
          return `${q(k)} = $${params.length}`;
        })
        .join(" and ");
      const sql = `delete from ${q(table)} where ${whereSql}`;
      const res = await query(profile, sql, params, { label: `delete from ${table}` });
      return NextResponse.json({ ok: true, rowCount: res.rowCount, sql, primaryKey: pk });
    }

    return NextResponse.json({ error: `unknown action: ${action}` }, { status: 400 });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message }, { status: 400 });
  }
}

/** Turn the UI's string inputs into something Postgres will accept. */
function coerce(v: unknown): unknown {
  if (typeof v !== "string") return v;
  const t = v.trim();
  if (t === "") return null;
  if (t === "null") return null;
  if (t === "true") return true;
  if (t === "false") return false;
  if (t.startsWith("{") || t.startsWith("[")) {
    try {
      JSON.parse(t);
      return t; // let pg cast the JSON text into json/jsonb
    } catch {
      return v;
    }
  }
  return v;
}
