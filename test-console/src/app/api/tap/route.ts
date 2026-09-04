import { NextRequest, NextResponse } from "next/server";
import { activeProfile } from "@/lib/profiles";
import {
  startApiLogTap,
  startRedisTap,
  startSqlTap,
  stopApiLogTap,
  stopRedisTap,
  stopSqlTap,
  tapStatus,
} from "@/lib/taps";
import { clearBuffer } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(tapStatus());
}

export async function POST(req: NextRequest) {
  const profile = await activeProfile();
  const { tap, on } = await req.json();

  if (tap === "clear") {
    clearBuffer();
    return NextResponse.json(tapStatus());
  }

  try {
    if (tap === "sql") on ? await startSqlTap(profile) : await stopSqlTap(profile);
    else if (tap === "redis") on ? await startRedisTap(profile) : await stopRedisTap();
    else if (tap === "apilog") on ? startApiLogTap() : stopApiLogTap();
    else return NextResponse.json({ error: `unknown tap: ${tap}` }, { status: 400 });
  } catch (err) {
    return NextResponse.json({ error: (err as Error).message, status: tapStatus() }, { status: 500 });
  }

  return NextResponse.json(tapStatus());
}
