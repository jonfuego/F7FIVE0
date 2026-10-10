// Pure Bearer-from-cookie logic, kept free of next/headers so it can be unit
// tested with node --test. api.ts wires it to the real cookie store and
// re-exports it; routes use accessBearer() from api.ts.

// Turn a raw access-cookie value into the Authorization header it belongs in.
// Returns null for a missing or empty cookie so callers can answer 401
// themselves instead of calling the API with no Bearer.
export function bearerFromCookieValue(access: string | undefined | null): string | null {
  return access ? `Bearer ${access}` : null;
}
