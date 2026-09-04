import { NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { query } from "@/lib/pg";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Live schema, introspected -- never hardcoded.
 * database/schema.sql in the Python repo is stale and diverges from
 * database/models.py; the real DDL is scripts/create_test_db.py.
 */
export async function GET() {
  const profile = await activeProfile();

  const cols = await query(
    profile,
    `select c.table_name,
            c.column_name,
            c.ordinal_position,
            c.data_type,
            c.udt_name,
            c.is_nullable,
            c.column_default,
            c.character_maximum_length
       from information_schema.columns c
       join information_schema.tables t
         on t.table_schema = c.table_schema and t.table_name = c.table_name
      where c.table_schema = 'public' and t.table_type = 'BASE TABLE'
      order by c.table_name, c.ordinal_position`,
    [],
    { label: "introspect columns", quiet: true },
  );

  const keys = await query(
    profile,
    `select tc.table_name,
            tc.constraint_type,
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name  as ref_table,
            ccu.column_name as ref_column
       from information_schema.table_constraints tc
       join information_schema.key_column_usage kcu
         on kcu.constraint_name = tc.constraint_name and kcu.table_schema = tc.table_schema
       left join information_schema.constraint_column_usage ccu
         on ccu.constraint_name = tc.constraint_name and ccu.table_schema = tc.table_schema
        and tc.constraint_type = 'FOREIGN KEY'
      where tc.table_schema = 'public'
        and tc.constraint_type in ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE')`,
    [],
    { label: "introspect constraints", quiet: true },
  );

  const idx = await query(
    profile,
    `select tablename as table_name, indexname, indexdef
       from pg_indexes where schemaname = 'public' order by tablename, indexname`,
    [],
    { label: "introspect indexes", quiet: true },
  );

  const tables = new Map<
    string,
    {
      name: string;
      columns: Record<string, unknown>[];
      primaryKey: string[];
      unique: { name: string; columns: string[] }[];
      foreignKeys: { column: string; refTable: string; refColumn: string }[];
      indexes: { name: string; def: string }[];
    }
  >();

  for (const row of cols.rows as Record<string, string>[]) {
    const t = row.table_name;
    if (!tables.has(t)) {
      tables.set(t, { name: t, columns: [], primaryKey: [], unique: [], foreignKeys: [], indexes: [] });
    }
    tables.get(t)!.columns.push(row);
  }

  const uniqueAccum = new Map<string, { table: string; name: string; columns: string[] }>();
  for (const row of keys.rows as Record<string, string>[]) {
    const entry = tables.get(row.table_name);
    if (!entry) continue;
    if (row.constraint_type === "PRIMARY KEY") {
      if (!entry.primaryKey.includes(row.column_name)) entry.primaryKey.push(row.column_name);
    } else if (row.constraint_type === "FOREIGN KEY") {
      const already = entry.foreignKeys.some(
        (f) => f.column === row.column_name && f.refTable === row.ref_table,
      );
      if (!already && row.ref_table) {
        entry.foreignKeys.push({ column: row.column_name, refTable: row.ref_table, refColumn: row.ref_column });
      }
    } else if (row.constraint_type === "UNIQUE") {
      const k = `${row.table_name}:${row.constraint_name}`;
      if (!uniqueAccum.has(k)) uniqueAccum.set(k, { table: row.table_name, name: row.constraint_name, columns: [] });
      const u = uniqueAccum.get(k)!;
      if (!u.columns.includes(row.column_name)) u.columns.push(row.column_name);
    }
  }
  for (const u of uniqueAccum.values()) {
    tables.get(u.table)?.unique.push({ name: u.name, columns: u.columns });
  }

  for (const row of idx.rows as Record<string, string>[]) {
    tables.get(row.table_name)?.indexes.push({ name: row.indexname, def: row.indexdef });
  }

  const list = Array.from(tables.values()).sort((a, b) => a.name.localeCompare(b.name));

  return NextResponse.json({
    tables: list,
    // Split for the UI: application tables vs LangGraph checkpointer tables.
    groups: {
      langgraph: list.filter((t) => t.name.startsWith("checkpoint")).map((t) => t.name),
      application: list.filter((t) => !t.name.startsWith("checkpoint")).map((t) => t.name),
    },
  });
}
