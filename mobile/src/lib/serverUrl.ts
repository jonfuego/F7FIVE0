/** Server address rules for the sign-in screen, as pure helpers so they unit-test
 * without the native modules (src/state/config.ts wires them up).
 *
 * A password and a refresh token go to this address, so a bare address only
 * defaults to cleartext http when it can only be reached from a private network.
 * Everything else defaults to https, and an explicit http:// to a public host
 * needs the person's confirmation before it is saved or a password is sent. */

/** The host part of what a person typed: scheme, credentials, port, path and
 * IPv6 brackets removed, lower-cased, trailing dot dropped. "" when there is none. */
export function hostOf(input: string): string {
  let s = (input ?? "").trim();
  s = s.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
  s = s.split(/[/?#]/)[0];
  const at = s.lastIndexOf("@");
  if (at >= 0) s = s.slice(at + 1);
  if (s.startsWith("[")) {
    const end = s.indexOf("]");
    return (end > 0 ? s.slice(1, end) : s.slice(1)).toLowerCase();
  }
  return s.split(":")[0].toLowerCase().replace(/\.$/, "");
}

function ipv4Octets(host: string): [number, number, number, number] | null {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return null;
  const o = [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])] as [number, number, number, number];
  return o.every((n) => n <= 255) ? o : null;
}

function privateIpv6(host: string): boolean {
  if (host === "::1") return true; // loopback
  if (!host.includes(":")) return false;
  const first = host.split(":")[0];
  if (first === "") return false;
  const lead = parseInt(first, 16);
  if (Number.isNaN(lead)) return false;
  if (lead >= 0xfe80 && lead <= 0xfebf) return true; // fe80::/10 link-local
  if (lead >= 0xfc00 && lead <= 0xfdff) return true; // fc00::/7 unique local
  return false;
}

/** True for a host that can only be a device or service on the local network:
 * localhost and loopback, RFC 1918 (10/8, 172.16/12, 192.168/16), link-local
 * 169.254/16, CGNAT 100.64/10 (Tailscale), `.local` names and single-label
 * names. IPv6 loopback, link-local and unique-local count too. A public IPv4
 * address, an out-of-range one and any dotted name are not private. */
export function isPrivateHost(host: string): boolean {
  const h = (host ?? "").trim().toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (!h) return false;
  if (h === "localhost" || h.endsWith(".localhost")) return true;
  const ip = ipv4Octets(h);
  if (ip) {
    const [a, b] = ip;
    if (a === 127) return true;
    if (a === 10) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 192 && b === 168) return true;
    if (a === 169 && b === 254) return true;
    if (a === 100 && b >= 64 && b <= 127) return true;
    return false;
  }
  if (h.includes(":")) return privateIpv6(h);
  if (/^[\d.]+$/.test(h)) return false; // numeric but not a valid IPv4 address
  if (h.endsWith(".local")) return true;
  return !h.includes(".");
}

/** "192.168.1.20:3001" -> "http://192.168.1.20:3001"; "media.example.com" and
 * "203.0.113.5" -> "https://...". An address with a scheme keeps it. Trailing
 * slashes are dropped. */
export function normalizeServerUrl(input: string): string {
  let s = (input ?? "").trim();
  if (!s) return "";
  if (!/^https?:\/\//i.test(s)) {
    s = `${isPrivateHost(hostOf(s)) ? "http" : "https"}://${s}`;
  }
  return s.replace(/\/+$/, "");
}

/** True when `url` is an explicit http:// address to a host that is not on a
 * private network: the password would cross the internet in the clear. */
export function isPublicCleartext(url: string): boolean {
  const s = (url ?? "").trim();
  if (!/^http:\/\//i.test(s)) return false;
  return !isPrivateHost(hostOf(s));
}

/** Wording for the confirmation shown before such an address is saved or used. */
export function cleartextWarning(url: string): { title: string; message: string; confirm: string } {
  const shown = (url ?? "").trim().replace(/\/+$/, "");
  return {
    title: "Unencrypted connection",
    message:
      `${shown} is a public address and does not use https. Your password and sign-in ` +
      "would travel across the internet unencrypted, where anyone on the way can read them. " +
      "Use an https:// address if your server has one.",
    confirm: "Use http anyway",
  };
}
