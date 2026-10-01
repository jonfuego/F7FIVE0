// Android app download for signed-in users.
//
// Serves the newest *.apk from F7FIVE0_DOWNLOADS_DIR (default
// C:\F7FIVE0\downloads). That folder sits outside C:\F7FIVE0\web because
// publish.ps1 mirrors the web target with /MIR and would wipe anything else
// there. The middleware already requires a session cookie for this path, so
// the download is only offered to people who can sign in to F7FIVE0.
//
// HEAD returns the same headers without the body; the Account page uses it
// to show the version and size, or hide the button when no APK is published.

import { createReadStream } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import path from "node:path";
import { Readable } from "node:stream";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const DOWNLOADS_DIR = process.env.F7FIVE0_DOWNLOADS_DIR ?? "C:\\F7FIVE0\\downloads";

async function newestApk(): Promise<{ file: string; name: string; size: number; mtime: Date } | null> {
  let names: string[];
  try {
    names = await readdir(DOWNLOADS_DIR);
  } catch {
    return null;
  }
  let best: { file: string; name: string; size: number; mtime: Date } | null = null;
  for (const name of names) {
    if (!name.toLowerCase().endsWith(".apk")) continue;
    const file = path.join(DOWNLOADS_DIR, name);
    const st = await stat(file).catch(() => null);
    if (!st || !st.isFile()) continue;
    if (!best || st.mtime > best.mtime) best = { file, name, size: st.size, mtime: st.mtime };
  }
  return best;
}

function headersFor(apk: { name: string; size: number; mtime: Date }): Headers {
  return new Headers({
    "content-type": "application/vnd.android.package-archive",
    "content-length": String(apk.size),
    "content-disposition": `attachment; filename="${apk.name.replace(/"/g, "")}"`,
    "last-modified": apk.mtime.toUTCString(),
    "x-apk-name": apk.name,
    "cache-control": "private, no-store",
  });
}

export async function HEAD(): Promise<Response> {
  const apk = await newestApk();
  if (!apk) return new Response(null, { status: 404 });
  return new Response(null, { status: 200, headers: headersFor(apk) });
}

export async function GET(): Promise<Response> {
  const apk = await newestApk();
  if (!apk) {
    return new Response("The Android app has not been published yet.", {
      status: 404,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
  const body = Readable.toWeb(createReadStream(apk.file)) as unknown as ReadableStream;
  return new Response(body, { status: 200, headers: headersFor(apk) });
}
