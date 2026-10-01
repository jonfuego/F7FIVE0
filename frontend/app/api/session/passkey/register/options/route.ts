// POST /api/session/passkey/register/options
//
// Authenticated (via the access cookie). Proxies to the backend
// /api/auth/passkey/register/options to mint a creation challenge and returns
// the PublicKeyCredentialCreationOptions for navigator.credentials.create.

import { NextResponse } from "next/server";
import { backend } from "@/lib/api";

export async function POST(): Promise<Response> {
  const res = await backend("/api/auth/passkey/register/options", {
    method: "POST",
    authed: true,
  });
  const payload = await res.json().catch(() => null);
  return NextResponse.json(payload ?? { detail: "passkey_options_failed" }, {
    status: res.status,
  });
}
