// The release app must be able to reach a plain-http server on the LAN.
// Without android:usesCleartextTraffic Android refuses http for apps targeting
// API 28+, and sign-in to http://192.168.x.x:3001 said "Can't reach that
// server" (1.0.18 and 1.0.19). The config plugin writes the flag on every
// `expo prebuild`; app.config.ts must keep listing it.
import fs from "fs";
import path from "path";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const plugin = require("../../../plugins/withCleartext.js") as {
  allowCleartext: (m: unknown) => {
    manifest: { application: { $: Record<string, string> }[] };
  };
};

function manifest(appAttrs: Record<string, string> = {}) {
  return {
    manifest: {
      $: {},
      application: [{ $: { "android:name": ".MainApplication", ...appAttrs } }],
    },
  };
}

describe("cleartext plugin", () => {
  it("allows cleartext on <application>", () => {
    const out = plugin.allowCleartext(manifest());
    expect(out.manifest.application[0].$["android:usesCleartextTraffic"]).toBe("true");
    expect(out.manifest.application[0].$["android:name"]).toBe(".MainApplication");
  });

  it("is idempotent and overrides a false value", () => {
    const once = plugin.allowCleartext(manifest({ "android:usesCleartextTraffic": "false" }));
    const twice = plugin.allowCleartext(once);
    expect(twice.manifest.application[0].$["android:usesCleartextTraffic"]).toBe("true");
  });

  it("is listed in app.config.ts", () => {
    const cfg = fs.readFileSync(path.join(__dirname, "../../../app.config.ts"), "utf8");
    expect(cfg).toContain('"./plugins/withCleartext.js"');
  });
});
