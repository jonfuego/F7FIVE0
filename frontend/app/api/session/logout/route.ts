// POST /api/session/logout
//
// Calls backend /api/auth/logout to revoke the current refresh session,
// then clears both cookies. We swallow any backend failure so the user
// always ends up logged out locally. Worst case: a revoked session row
// sticks around until its natural expiry, but the tokens are gone from
// this browser either way.

import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { backend } from "@/lib/api";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/server-env";
import { clearSessionCookies } from "@/lib/cookies";

export async function POST() {
  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;
  const refresh = jar.get(REFRESH_COOKIE)?.value;

  if (access && refresh) {
    try {
      await backend("/api/auth/logout", {
        method: "POST",
        headers: { authorization: `Bearer ${access}` },
        body: { refresh_token: refresh },
      });
    } catch {
      // Ignored on purpose. See note above.
    }
  }

  const res = NextResponse.json({ ok: true }, { status: 200 });
  await clearSessionCookies(res);
  return res;
}
