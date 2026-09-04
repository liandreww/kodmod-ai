import { NextRequest, NextResponse } from "next/server";
import { activeProfile, publicProfile } from "@/lib/profiles";
import { encodeSession, readSession, SESSION_COOKIE } from "@/lib/session";
import { inspectToken, mintAlgNoneToken, mintToken } from "@/lib/jwt";
import { publish } from "@/lib/bus";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const profile = await activeProfile();
  const session = await readSession();
  return NextResponse.json({
    profile: publicProfile(profile),
    session: session
      ? { ...session, inspect: inspectToken(session.token, profile.jwtSecret, profile.jwtAlg) }
      : null,
  });
}

export async function POST(req: NextRequest) {
  const profile = await activeProfile();
  const payload = await req.json();
  const action = payload.action as string;

  if (action === "signout") {
    publish("system", "sign out");
    const res = NextResponse.json({ ok: true });
    res.cookies.delete(SESSION_COOKIE);
    return res;
  }

  if (action === "inspect") {
    return NextResponse.json({
      inspect: inspectToken(String(payload.token ?? ""), profile.jwtSecret, profile.jwtAlg),
    });
  }

  if (action === "signin") {
    const sub = String(payload.sub ?? "").trim();
    const role = String(payload.role ?? "student");
    const displayName = String(payload.displayName ?? sub);
    const ttlSeconds = Number(payload.ttlSeconds ?? 3600);
    const secret = payload.secretOverride ? String(payload.secretOverride) : profile.jwtSecret;
    const alg = String(payload.alg ?? profile.jwtAlg);
    const expiredBySeconds = Number(payload.expiredBySeconds ?? 0);

    let token: string;
    let note: string | undefined;

    if (payload.algNone) {
      token = mintAlgNoneToken(sub, role, ttlSeconds);
      note = "alg=none token (expected to be rejected)";
    } else if (payload.rawToken) {
      token = String(payload.rawToken);
      note = "pasted token";
    } else {
      token = mintToken({ sub, role, ttlSeconds, secret, alg, expiredBySeconds });
      if (payload.secretOverride) note = "signed with a non-matching secret (expected 401)";
      else if (expiredBySeconds > 0) note = `back-dated by ${expiredBySeconds}s (expected 401 Token expired)`;
    }

    const session = { token, sub, role, displayName, profile: profile.name, note };
    publish("system", `sign in as ${role} ${displayName}`, { detail: { sub, note } });

    const res = NextResponse.json({
      ok: true,
      session,
      inspect: inspectToken(token, profile.jwtSecret, profile.jwtAlg),
    });
    res.cookies.set(SESSION_COOKIE, encodeSession(session), {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24,
    });
    return res;
  }

  return NextResponse.json({ error: `unknown action: ${action}` }, { status: 400 });
}
