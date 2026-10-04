// PATCH / DELETE /api/session/passkey/credentials/{id}
//
// Authenticated. Rename or delete one of the signed-in user's passkeys by
// proxying to the backend /api/auth/passkeys/{id}.

import { NextRequest, NextResponse } from "next/server";
import { backend } from "@/lib/api";

export async function PATCH(req: NextRequest, props: { params: Promise<{ id: string }> }): Promise<Response> {
  const params = await props.params;
  let body: { name?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "invalid_json" }, { status: 400 });
  }
  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!name) {
    return NextResponse.json({ detail: "name_required" }, { status: 400 });
  }
  const res = await backend(`/api/auth/passkeys/${encodeURIComponent(params.id)}`, {
    method: "PATCH",
    authed: true,
    body: { name: name.slice(0, 120) },
  });
  const payload = await res.json().catch(() => null);
  return NextResponse.json(payload ?? { detail: "passkey_rename_failed" }, {
    status: res.status,
  });
}

export async function DELETE(_req: NextRequest, props: { params: Promise<{ id: string }> }): Promise<Response> {
  const params = await props.params;
  const res = await backend(`/api/auth/passkeys/${encodeURIComponent(params.id)}`, {
    method: "DELETE",
    authed: true,
  });
  if (res.status === 204) return new NextResponse(null, { status: 204 });
  const payload = await res.json().catch(() => null);
  return NextResponse.json(payload ?? { detail: "passkey_delete_failed" }, {
    status: res.status,
  });
}
