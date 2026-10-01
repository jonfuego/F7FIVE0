// POST /api/session/passkey/login/options
//
// Unauthenticated. Proxies to the backend to mint a WebAuthn assertion
// challenge and returns the PublicKeyCredentialRequestOptions JSON the browser
// hands to navigator.credentials.get.

import { NextResponse } from "next/server";
import { backend } from "@/lib/api";

export async function POST(): Promise<Response> {
  const res = await backend("/api/auth/passkey/login/options", { method: "POST" });
  const payload = await res.json().catch(() => null);
  return NextResponse.json(payload ?? { detail: "passkey_options_failed" }, {
    status: res.status,
  });
}
