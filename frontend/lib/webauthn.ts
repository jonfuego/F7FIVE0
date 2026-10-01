// Browser-side WebAuthn helpers for passkey sign-in and registration.
//
// The backend returns options as base64url JSON (py_webauthn's options_to_json);
// the WebAuthn DOM API wants ArrayBuffers for `challenge`, credential ids and
// `user.id`, and returns ArrayBuffers we have to re-encode as base64url before
// posting back. These helpers do that conversion and drive
// navigator.credentials.get / .create through the /api/session/passkey BFF, so
// tokens still only ever live in httpOnly cookies.

"use client";

function base64urlToBuffer(value: string): ArrayBuffer {
  const pad = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes.buffer;
}

function bufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Whether this browser can do platform passkeys at all. Used to hide the
// button on browsers that will never support it.
export function passkeysSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    !!navigator.credentials
  );
}

interface PublicKeyOptions {
  challenge: string;
  allowCredentials?: { id: string; type: string; transports?: string[] }[];
  excludeCredentials?: { id: string; type: string; transports?: string[] }[];
  user?: { id: string; name: string; displayName: string };
  [k: string]: unknown;
}

function serializeCredential(cred: PublicKeyCredential): Record<string, unknown> {
  const response = cred.response as
    | AuthenticatorAttestationResponse
    | AuthenticatorAssertionResponse;
  const out: Record<string, unknown> = {
    id: cred.id,
    rawId: bufferToBase64url(cred.rawId),
    type: cred.type,
    clientExtensionResults: cred.getClientExtensionResults(),
  };
  const res: Record<string, unknown> = {
    clientDataJSON: bufferToBase64url(response.clientDataJSON),
  };
  if ("attestationObject" in response) {
    res.attestationObject = bufferToBase64url(response.attestationObject);
    const transports = (response as AuthenticatorAttestationResponse).getTransports?.();
    if (transports && transports.length) res.transports = transports;
  } else {
    const asr = response as AuthenticatorAssertionResponse;
    res.authenticatorData = bufferToBase64url(asr.authenticatorData);
    res.signature = bufferToBase64url(asr.signature);
    if (asr.userHandle) res.userHandle = bufferToBase64url(asr.userHandle);
  }
  out.response = res;
  return out;
}

// Sign in with an existing passkey. Returns the serialized assertion the BFF
// verify route forwards to the backend.
export async function getPasskeyAssertion(): Promise<Record<string, unknown>> {
  const res = await fetch("/api/session/passkey/login/options", { method: "POST" });
  if (!res.ok) throw new Error("could not start passkey sign-in");
  const options = (await res.json()) as PublicKeyOptions;

  const publicKey: PublicKeyCredentialRequestOptions = {
    ...(options as unknown as PublicKeyCredentialRequestOptions),
    challenge: base64urlToBuffer(options.challenge),
    allowCredentials: (options.allowCredentials ?? []).map((c) => ({
      id: base64urlToBuffer(c.id),
      type: "public-key",
      transports: c.transports as AuthenticatorTransport[] | undefined,
    })),
  };

  const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error("passkey sign-in was cancelled");
  return serializeCredential(cred);
}

// Create a new passkey for the signed-in user. Returns the serialized
// attestation the BFF register/verify route forwards to the backend.
export async function createPasskey(): Promise<Record<string, unknown>> {
  const res = await fetch("/api/session/passkey/register/options", { method: "POST" });
  if (!res.ok) throw new Error("could not start passkey registration");
  const options = (await res.json()) as PublicKeyOptions;

  const publicKey: PublicKeyCredentialCreationOptions = {
    ...(options as unknown as PublicKeyCredentialCreationOptions),
    challenge: base64urlToBuffer(options.challenge),
    user: {
      ...(options.user as unknown as PublicKeyCredentialUserEntity),
      id: base64urlToBuffer(options.user!.id),
    },
    excludeCredentials: (options.excludeCredentials ?? []).map((c) => ({
      id: base64urlToBuffer(c.id),
      type: "public-key",
      transports: c.transports as AuthenticatorTransport[] | undefined,
    })),
  };

  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error("passkey registration was cancelled");
  return serializeCredential(cred);
}
