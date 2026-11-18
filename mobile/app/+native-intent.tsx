import { redirectSystemPath as route } from "@/lib/nativeIntent";

/** System links (the media notification tap) before the router sees them.
 * The rules are in src/lib/nativeIntent.ts. Never throw here: an error in this
 * hook can crash the app on launch. */
export function redirectSystemPath({ path, initial }: { path: string; initial: boolean }): string {
  try {
    return route(path, initial);
  } catch {
    return initial ? "/" : "";
  }
}
