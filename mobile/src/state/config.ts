import Constants from "expo-constants";
import { requireOptionalNativeModule } from "expo-modules-core";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { chooseServer, parseStamp } from "@/lib/serverStamp";

interface Extra {
  apiBase?: string;
  isTv?: boolean;
}

const extra = (Constants.expoConfig?.extra ?? {}) as Extra;

// The server address is chosen on the sign-in screen and saved on the device,
// so one build works against anyone's F7FIVE0 server. A copy downloaded from a
// server carries that server's addresses in its APK (the "stamp"), which fill
// the sign-in screen on first launch. A build can still bake a default in
// with EXPO_PUBLIC_API_BASE (app.config.ts -> extra.apiBase).
const SERVER_KEY = "f7five0.server_url";
const STAMP_KEY = "f7five0.stamped_servers";
const PROBE_TIMEOUT_MS = 3000;
let apiBase = normalizeServerUrl(extra.apiBase ?? "");
let filledFromStamp = false;

/** Current server origin, e.g. "https://media.example.com" or
 * "http://192.168.1.20:3001". Empty until one has been chosen. Read it at call
 * time; it changes when the user picks a different server. */
export function getApiBase(): string {
  return apiBase;
}

/** "192.168.1.20:3001" -> "http://192.168.1.20:3001"; "media.example.com" ->
 * "https://media.example.com". Trailing slashes are dropped. */
export function normalizeServerUrl(input: string): string {
  let s = (input ?? "").trim();
  if (!s) return "";
  if (!/^https?:\/\//i.test(s)) {
    const host = s.split("/")[0].split(":")[0];
    const local =
      host === "localhost" ||
      /^\d{1,3}(\.\d{1,3}){3}$/.test(host) ||
      host.endsWith(".local") ||
      !host.includes(".");
    s = `${local ? "http" : "https"}://${s}`;
  }
  return s.replace(/\/+$/, "");
}

/** Load the saved server (app launch). Falls back to the baked-in default. */
export async function loadServerUrl(): Promise<string> {
  try {
    const saved = await SecureStore.getItemAsync(SERVER_KEY);
    if (saved) apiBase = normalizeServerUrl(saved);
  } catch {
    // Keystore unavailable: keep the default.
  }
  return apiBase;
}

interface StampNative {
  readStamp(): Promise<string | null>;
}

/** Addresses stamped into this app's APK by the server it came from, or []
 * (built locally, installed from GitHub, or not Android). */
export async function readStampedServers(): Promise<string[]> {
  try {
    const native = requireOptionalNativeModule<StampNative>("F7FIVE0Stamp");
    return parseStamp(native ? await native.readStamp() : null);
  } catch {
    return [];
  }
}

async function answers(origin: string): Promise<boolean> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(`${origin}/api/client/min-version`, { signal: ctrl.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

/** First launch: when no server is saved, use the stamped addresses. Picks
 * the first one that answers (public address first) and keeps the full list
 * for later network switching. Nothing is saved as the server until sign-in. */
export async function fillServerFromStamp(): Promise<void> {
  if (apiBase) return;
  const servers = await readStampedServers();
  if (servers.length === 0) return;
  try {
    await SecureStore.setItemAsync(STAMP_KEY, JSON.stringify(servers));
  } catch {
    // Only needed later; the address below still works this session.
  }
  apiBase = await chooseServer(servers, answers);
  filledFromStamp = apiBase !== "";
}

/** True when the current server came from the APK stamp and the person has
 * not changed it yet (the sign-in screen says so). */
export function serverFilledFromStamp(): boolean {
  return filledFromStamp;
}

/** Remember a server chosen on the sign-in screen. */
export async function saveServerUrl(input: string): Promise<string> {
  const next = normalizeServerUrl(input);
  if (next !== apiBase) filledFromStamp = false;
  apiBase = next;
  try {
    await SecureStore.setItemAsync(SERVER_KEY, apiBase);
  } catch {
    // Still usable for this session.
  }
  return apiBase;
}

export const IS_TV = extra.isTv === true || Platform.isTV === true;

export const APP_VERSION = Constants.expoConfig?.version ?? "1.0.0";

/** Platform key used for the min-version gate and the login device metadata. */
export function clientPlatform(): "android" | "ios" | "android_tv" | "tvos" {
  if (Platform.OS === "ios") return IS_TV ? "tvos" : "ios";
  return IS_TV ? "android_tv" : "android";
}

export function deviceName(): string {
  return Constants.deviceName ?? `${Platform.OS} device`;
}
