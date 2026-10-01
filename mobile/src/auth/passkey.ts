/** Native passkey client (WebAuthn via Android Credential Manager).
 *
 * react-native-passkey drives the platform prompt (fingerprint / device lock,
 * backed by Google Password Manager on the Pixel). The backend mints and
 * verifies challenges; this module is the glue:
 *
 *  - registerPasskey: authenticated. Fetch creation options, run the platform
 *    create ceremony, post the attestation back to be stored.
 *  - passkeyLogin: unauthenticated. Fetch assertion options, run the get
 *    ceremony, post the assertion; the backend returns a native TokenPair.
 *
 * Login runs against the chosen server directly (no session yet); the caller
 * adopts the returned pair into the ApiClient. Registration goes through the
 * authenticated ApiClient. The Android WebAuthn origin is the app's
 * apk-key-hash, resolved by Credential Manager from the server's
 * /.well-known/assetlinks.json, so the server must list this app's signing
 * certificate (WEBAUTHN_ANDROID_CERT_SHA256; the official cert by default).
 *
 * Passkeys need an https server: `serverHasPasskeys` asks the server
 * (/api/client/features) before the login screen offers the button. Android
 * TV has no passkey UI, so TV builds never offer it.
 */
import { Passkey } from "react-native-passkey";

import type { ApiClient } from "@/api/client";
import { APP_VERSION, IS_TV, clientPlatform, deviceName, getApiBase } from "@/state/config";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

/** A registered passkey as returned by GET /api/auth/passkeys. Never carries
 * key material (public key / raw credential id). */
export interface PasskeyDTO {
  id: string;
  name: string;
  transports?: string | null;
  aaguid?: string | null;
  created_at: string;
  last_used_at?: string | null;
}

// react-native-passkey results omit `type`; py_webauthn requires
// type:"public-key". Normalize before sending either credential.
function withType(cred: Record<string, unknown>): Record<string, unknown> {
  return { type: "public-key", ...cred };
}

/** Whether the platform can do passkeys (Play services + a screen lock). */
export function passkeysAvailable(): boolean {
  if (IS_TV) return false;
  try {
    return Passkey.isSupported();
  } catch {
    return false;
  }
}

/** Register a new passkey for the signed-in user. Throws on cancel/failure. */
export async function registerPasskey(api: ApiClient, name?: string): Promise<void> {
  // Passkey.create expects the standard WebAuthn creation options JSON, which is
  // exactly what the backend returns (options_to_json).
  const options = await api.json<Parameters<typeof Passkey.create>[0]>(
    "/api/auth/passkey/register/options",
    { method: "POST" },
  );
  const attestation = (await Passkey.create(options)) as unknown as Record<string, unknown>;
  await api.json("/api/auth/passkey/register/verify", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ credential: withType(attestation), name: name ?? null }),
  });
}

/** List the signed-in user's passkeys. */
export async function listPasskeys(api: ApiClient): Promise<PasskeyDTO[]> {
  return api.json<PasskeyDTO[]>("/api/auth/passkeys");
}

/** Rename one of the user's passkeys (PATCH /api/auth/passkeys/{id}). */
export async function renamePasskey(
  api: ApiClient,
  id: string,
  name: string,
): Promise<PasskeyDTO> {
  return api.json<PasskeyDTO>(`/api/auth/passkeys/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

/** Delete one of the user's passkeys (DELETE /api/auth/passkeys/{id}). */
export async function deletePasskey(api: ApiClient, id: string): Promise<void> {
  const res = await api.request(`/api/auth/passkeys/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`passkey_delete_failed_${res.status}`);
  }
}

/** Sign in with an existing passkey. Returns a native TokenPair the caller
 * adopts into the ApiClient. Throws on cancel/failure. */
export async function passkeyLogin(): Promise<TokenPair> {
  const base = getApiBase();
  if (!base) throw new Error("no_server");
  const optRes = await fetch(`${base}/api/auth/passkey/login/options`, {
    method: "POST",
  });
  if (!optRes.ok) throw new Error("passkey_options_failed");
  const options = (await optRes.json()) as Parameters<typeof Passkey.get>[0];

  const assertion = (await Passkey.get(options)) as unknown as Record<string, unknown>;

  const verifyRes = await fetch(`${base}/api/auth/passkey/login/verify`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      credential: withType(assertion),
      client_type: "native",
      device_name: deviceName(),
      platform: clientPlatform(),
      client_version: APP_VERSION,
    }),
  });
  if (verifyRes.status === 401) throw new Error("invalid_passkey");
  if (!verifyRes.ok) throw new Error(`passkey_login_failed_${verifyRes.status}`);
  return (await verifyRes.json()) as TokenPair;
}

/** Whether the server at `base` (a normalized origin) has passkeys on. Any
 * failure (unreachable, older server without the flag) counts as off. */
export async function serverHasPasskeys(
  base: string,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  if (!base.startsWith("https://")) return false;
  try {
    const res = await fetchImpl(`${base}/api/client/features`);
    if (!res.ok) return false;
    const body = (await res.json()) as { passkeys?: { enabled?: boolean } };
    return body.passkeys?.enabled === true;
  } catch {
    return false;
  }
}
