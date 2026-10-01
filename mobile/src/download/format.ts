/** Byte-size formatting for the Downloads screen (crit 42). Pure so it unit
 * tests in Node. */

/** Human-readable size (KB/MB/GB, 1 decimal). 0 bytes shows as "0 B". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n = bytes;
  let u = 0;
  while (n >= 1024 && u < units.length - 1) {
    n /= 1024;
    u += 1;
  }
  const rounded = u === 0 ? Math.round(n) : Math.round(n * 10) / 10;
  return `${rounded} ${units[u]}`;
}

/** Fraction of the storage limit used (0..1), or null when unlimited. */
export function limitFraction(usedBytes: number, limitBytes: number): number | null {
  if (limitBytes <= 0) return null;
  return Math.min(1, usedBytes / limitBytes);
}
