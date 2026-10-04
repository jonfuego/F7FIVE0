/** Server addresses stamped into the APK by the server it was downloaded
 * from (backend/app/services/android_app.py). Pure helpers, so they unit-test
 * without the native module; src/state/config.ts wires them up.
 *
 * Stamp JSON: {"v":1,"servers":["https://media.example.com","http://192.168.1.20:3001"]}
 * Order is the server's preference: public address, the address the APK was
 * downloaded from, home network address.
 */

const MAX_SERVERS = 8;

/** The http(s) origins in a stamp, in order, or [] when it is missing or
 * malformed. Never throws. */
export function parseStamp(raw: string | null | undefined): string[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!data || typeof data !== "object") return [];
  const servers = (data as { servers?: unknown }).servers;
  if (!Array.isArray(servers)) return [];
  const out: string[] = [];
  for (const s of servers) {
    if (typeof s !== "string") continue;
    const m = /^(https?):\/\/([^/?#\s]+)\/?$/i.exec(s.trim());
    if (!m) continue;
    const origin = `${m[1].toLowerCase()}://${m[2]}`;
    if (!out.includes(origin)) out.push(origin);
    if (out.length >= MAX_SERVERS) break;
  }
  return out;
}

/** Pick the server to use: the first address (in stamp order) that answers.
 * All are probed at once so a dead home address costs one timeout, not one
 * per address. Falls back to the first address when none answer (offline at
 * first launch): the sign-in screen still shows it and the person can edit it. */
export async function chooseServer(
  servers: string[],
  probe: (origin: string) => Promise<boolean>,
): Promise<string> {
  if (servers.length === 0) return "";
  const results = servers.map((s) => probe(s).catch(() => false));
  for (let i = 0; i < servers.length; i++) {
    if (await results[i]) return servers[i];
  }
  return servers[0];
}
