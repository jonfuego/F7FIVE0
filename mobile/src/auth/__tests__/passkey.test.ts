// Passkey glue: server capability check and the native login request shape.
// react-native-passkey and the Expo config module are mocked so this runs in
// plain Node. jest.mock calls are hoisted above the import.

import { passkeyLogin, passkeysAvailable, serverHasPasskeys } from "../passkey";

const mockGet = jest.fn();
let mockIsTv = false;
let mockBase = "https://media.example.com";

jest.mock("react-native-passkey", () => ({
  Passkey: { isSupported: () => true, get: (o: unknown) => mockGet(o), create: jest.fn() },
}));
jest.mock("@/state/config", () => ({
  get IS_TV() {
    return mockIsTv;
  },
  APP_VERSION: "1.0.0",
  clientPlatform: () => "android",
  deviceName: () => "Pixel",
  getApiBase: () => mockBase,
}));

function res(status: number, body: unknown): Response {
  return { status, ok: status >= 200 && status < 300, json: async () => body } as unknown as Response;
}

describe("serverHasPasskeys", () => {
  it("is false for plain http without asking the server", async () => {
    const f = jest.fn();
    await expect(serverHasPasskeys("http://192.168.1.20:3001", f as unknown as typeof fetch)).resolves.toBe(false);
    expect(f).not.toHaveBeenCalled();
  });

  it("reads the features flag", async () => {
    const on = jest.fn(async () => res(200, { passkeys: { enabled: true } }));
    await expect(serverHasPasskeys("https://media.example.com", on as unknown as typeof fetch)).resolves.toBe(true);
    expect(on).toHaveBeenCalledWith("https://media.example.com/api/client/features");
    const off = jest.fn(async () => res(200, { requests: { enabled: false } }));
    await expect(serverHasPasskeys("https://old.example.com", off as unknown as typeof fetch)).resolves.toBe(false);
  });

  it("treats errors as off", async () => {
    const boom = jest.fn(async () => {
      throw new TypeError("Network request failed");
    });
    await expect(serverHasPasskeys("https://media.example.com", boom as unknown as typeof fetch)).resolves.toBe(false);
    const bad = jest.fn(async () => res(500, {}));
    await expect(serverHasPasskeys("https://media.example.com", bad as unknown as typeof fetch)).resolves.toBe(false);
  });
});

describe("passkeysAvailable", () => {
  it("is off on TV builds", () => {
    mockIsTv = true;
    expect(passkeysAvailable()).toBe(false);
    mockIsTv = false;
    expect(passkeysAvailable()).toBe(true);
  });
});

describe("passkeyLogin", () => {
  const realFetch = global.fetch;
  afterEach(() => {
    global.fetch = realFetch;
    mockBase = "https://media.example.com";
  });

  it("posts the assertion to the chosen server as a native client", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith("/login/options")) return res(200, { challenge: "abc", rpId: "media.example.com" });
      return res(200, { access_token: "a", refresh_token: "r" });
    }) as unknown as typeof fetch;
    mockGet.mockResolvedValue({ id: "cred", rawId: "cred", response: {} });

    await expect(passkeyLogin()).resolves.toEqual({ access_token: "a", refresh_token: "r" });
    expect(calls.map((c) => c.url)).toEqual([
      "https://media.example.com/api/auth/passkey/login/options",
      "https://media.example.com/api/auth/passkey/login/verify",
    ]);
    const body = JSON.parse(String(calls[1].init?.body));
    expect(body.client_type).toBe("native");
    expect(body.credential.type).toBe("public-key");
    expect(body.device_name).toBe("Pixel");
  });

  it("maps 401 to invalid_passkey and refuses with no server", async () => {
    global.fetch = jest.fn(async (url: string) =>
      url.endsWith("/login/options") ? res(200, { challenge: "abc" }) : res(401, {}),
    ) as unknown as typeof fetch;
    mockGet.mockResolvedValue({ id: "cred", response: {} });
    await expect(passkeyLogin()).rejects.toThrow("invalid_passkey");
    mockBase = "";
    await expect(passkeyLogin()).rejects.toThrow("no_server");
  });
});
