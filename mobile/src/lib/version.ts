/** Semantic-version comparison for the launch min-version gate.
 *
 * Pure and dependency-free so it unit-tests without any native modules. The
 * app calls GET /api/client/min-version on launch; if the installed build is
 * below the floor for its platform, it shows the "Update required" screen.
 */

export type Platform = "android" | "ios" | "android_tv" | "tvos";

export interface MinClientVersions {
  android: string;
  ios: string;
  android_tv: string;
  tvos: string;
}

function parse(v: string): number[] {
  return v
    .trim()
    .split(".")
    .map((p) => {
      const n = parseInt(p, 10);
      return Number.isFinite(n) ? n : 0;
    });
}

/** -1 if a<b, 0 if equal, 1 if a>b. Missing components are treated as 0, so
 * "1.2" == "1.2.0". */
export function compareVersion(a: string, b: string): number {
  const pa = parse(a);
  const pb = parse(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x < y) return -1;
    if (x > y) return 1;
  }
  return 0;
}

/** True when the installed build is strictly older than the required floor. */
export function isUpdateRequired(current: string, minimum: string): boolean {
  return compareVersion(current, minimum) < 0;
}

/** Resolve the floor for a platform and compare against the current build. */
export function isUpdateRequiredForPlatform(
  current: string,
  platform: Platform,
  mins: MinClientVersions,
): boolean {
  const floor = mins[platform] ?? "0.0.0";
  return isUpdateRequired(current, floor);
}
