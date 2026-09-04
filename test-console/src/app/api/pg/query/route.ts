import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import { looksReadOnly, presentRows, query } from "@/lib/pg";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Free-form SQL runner. Read-only by default; writes require allowWrite,
 * which the UI only sends after an explicit confirmation.
 */
export async function POST(req: NextRequest) {
  const profile = await activeProfile();
  const { sql, allowWrite } = await req.json();
  const text = String(sql ?? "").trim();

  if (!text) return NextResponse.json({ error: "empty statement" }, { status: 400 });

  const readOnly = looksReadOnly(text);
  if (!readOnly && !allowWrite) {
    return NextResponse.json(
      { error: "statement looks like a write; enable write mode to run it", readOnly: false },
      { status: 400 },
    );
  }

  try {
    const res = await query(profile, text, [], { label: allowWrite && !readOnly ? "SQL (write mode)" : "SQL" });
    return NextResponse.json({
      ok: true,
      command: res.command,
      rowCount: res.rowCount,
      durationMs: res.durationMs,
      fields: res.fields.map((f) => f.name),
      rows: presentRows(res.rows),
      readOnly,
    });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message, readOnly }, { status: 400 });
  }
}
