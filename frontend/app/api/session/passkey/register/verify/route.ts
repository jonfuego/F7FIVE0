// POST /api/session/passkey/register/verify
//
// Authenticated. Forwards the WebAuthn attestation plus an optional label to
// the backend /api/auth/passkey/register/verify, which persists the credential.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export async function POST(req: NextRequest): Promise<Response> {
  let body: { credential?: unknown; name?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "invalid_json" }, { status: 400 });
  }
  if (!body.credential || typeof body.credential !== "object") {
    return NextResponse.json({ detail: "missing_credential" }, { status: 400 });
  }

  const res = await backend("/api/auth/passkey/register/verify", {
    method: "POST",
    authed: true,
    body: {
      credential: body.credential,
      name: typeof body.name === "string" ? body.name.slice(0, 120) : null,
    },
  });
  const payload = await res.json().catch(() => null);
  return NextResponse.json(payload ?? { detail: "passkey_register_failed" }, {
    status: res.status,
  });
}
