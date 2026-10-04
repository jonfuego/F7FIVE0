/** "Update from your server": the phone app this server hands out, and
 * whether it is newer than the installed build. Pure, so it unit-tests
 * without React Native. */
import { compareVersion } from "@/lib/version";

/** GET /api/client/android-app */
export interface ServerAppInfo {
  available: boolean;
  version?: string;
  abi?: string;
  abis?: string[];
  file_name?: string;
  size_bytes?: number;
  /** Signed one-hour download link a browser can open. */
  url?: string;
  path?: string;
}

/** The server's app version when it is newer than this build, else null.
 * Older server builds are never offered: Android refuses a downgrade. */
export function newerServerVersion(installed: string, info: ServerAppInfo | null | undefined): string | null {
  if (!info?.available || !info.version || !info.url) return null;
  return compareVersion(info.version, installed) > 0 ? info.version : null;
}

/** Download size for display, e.g. "34 MB". */
export function formatSize(bytes: number | undefined): string {
  if (!bytes || bytes <= 0) return "";
  return `${Math.max(1, Math.round(bytes / (1024 * 1024)))} MB`;
}
