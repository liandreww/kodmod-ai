import { NextRequest, NextResponse } from "next/server";
import { getProfile, publicProfile, type ProfileName } from "@/lib/profiles";
import { PROFILE_COOKIE, SESSION_COOKIE } from "@/lib/session";
import { publish } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    profiles: [publicProfile(getProfile("test")), publicProfile(getProfile("dev"))],
  });
}

export async function POST(req: NextRequest) {
  const { name } = await req.json();
  const target: ProfileName = name === "dev" ? "dev" : "test";
  publish("system", `switch profile -> ${target}`);

  const res = NextResponse.json({ ok: true, profile: publicProfile(getProfile(target)) });
  res.cookies.set(PROFILE_COOKIE, target, { sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 30 });
  // The JWT secret differs per profile, so the old token would fail signature checks.
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
