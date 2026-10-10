// Passkey-specific error text for the login page. Kept apart from the password
// friendlyError so a passkey failure never reads "Username or password is
// incorrect." and a server error does not use the generic wording.

export function passkeyErrorMessage(status: number, payload: unknown): string {
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? String((payload as { detail?: unknown }).detail ?? "")
      : "";

  if (status === 429 || detail === "too_many_attempts") {
    return "Too many passkey attempts. Wait a few minutes or use your password.";
  }
  if (status === 404 || detail === "passkeys_disabled") {
    return "Passkeys are not available on this server. Use your password.";
  }
  if (detail === "unknown_passkey") {
    return "This passkey is not registered here. Use your password, or add it again in Settings.";
  }
  if (status === 400 || detail === "invalid_credential") {
    return "Your device sent a passkey response the server could not read. Try again or use your password.";
  }
  if (status === 401 || status === 403) {
    return "Passkey could not be verified. Try again or use your password.";
  }
  if (status >= 500) {
    return "Passkey sign-in hit a server problem. Try again, or use your password.";
  }
  return "Passkey sign-in failed. Use your password.";
}
