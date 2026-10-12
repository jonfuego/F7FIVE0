import {
  cleartextWarning,
  hostOf,
  isPrivateHost,
  isPublicCleartext,
  normalizeServerUrl,
} from "../serverUrl";

describe("hostOf", () => {
  it.each([
    ["192.168.1.20:3001", "192.168.1.20"],
    ["http://192.168.1.20:3001/", "192.168.1.20"],
    ["https://Media.Example.com/some/path?x=1", "media.example.com"],
    ["user:pw@media.example.com:8443", "media.example.com"],
    ["[::1]:3001", "::1"],
    ["http://[fe80::1]/", "fe80::1"],
    ["mediabox", "mediabox"],
    ["mediabox.", "mediabox"],
    ["", ""],
  ])("%p -> %p", (input, host) => {
    expect(hostOf(input)).toBe(host);
  });
});

describe("isPrivateHost", () => {
  it.each(["localhost", "LOCALHOST", "app.localhost", "127.0.0.1", "127.8.9.10", "::1", "[::1]"])(
    "%p (localhost and loopback) is private",
    (host) => {
      expect(isPrivateHost(host)).toBe(true);
    },
  );

  it.each([
    "10.0.0.1",
    "10.255.255.254",
    "172.16.0.1",
    "172.20.5.5",
    "172.31.255.254",
    "192.168.0.1",
    "192.168.1.20",
  ])("%p (RFC 1918) is private", (host) => {
    expect(isPrivateHost(host)).toBe(true);
  });

  it.each(["169.254.0.1", "169.254.169.254"])("%p (link-local) is private", (host) => {
    expect(isPrivateHost(host)).toBe(true);
  });

  it.each(["100.64.0.1", "100.64.1.1", "100.100.100.100", "100.127.255.254"])(
    "%p (CGNAT / Tailscale) is private",
    (host) => {
      expect(isPrivateHost(host)).toBe(true);
    },
  );

  it.each(["mediabox.local", "nas.LOCAL", "mediabox", "fuegonas", "hive"])(
    "%p (.local or a single label) is private",
    (host) => {
      expect(isPrivateHost(host)).toBe(true);
    },
  );

  it.each(["fe80::1", "fd12:3456::1", "fc00::5"])("%p (IPv6 link-local or unique-local) is private", (host) => {
    expect(isPrivateHost(host)).toBe(true);
  });

  it.each([
    "203.0.113.5",
    "8.8.8.8",
    "93.184.216.34",
    "172.15.255.255",
    "172.32.0.1",
    "100.63.255.255",
    "100.128.0.1",
    "192.169.0.1",
    "11.0.0.1",
    "169.253.1.1",
  ])("%p (public IPv4, including just outside each private range) is not private", (host) => {
    expect(isPrivateHost(host)).toBe(false);
  });

  it.each(["media.example.com", "example.com", "a.b.c.example.org", "nas.home.arpa", "mediabox.lan"])(
    "%p (dotted name) is not private",
    (host) => {
      expect(isPrivateHost(host)).toBe(false);
    },
  );

  it.each(["2606:4700:4700::1111", "2001:db8::1"])("%p (public IPv6) is not private", (host) => {
    expect(isPrivateHost(host)).toBe(false);
  });

  it("an out-of-range or partial number is not treated as a private address", () => {
    expect(isPrivateHost("999.1.1.1")).toBe(false);
    expect(isPrivateHost("10.0.0")).toBe(false);
    expect(isPrivateHost("300.300.300.300")).toBe(false);
  });

  it("empty is not private", () => {
    expect(isPrivateHost("")).toBe(false);
  });
});

describe("normalizeServerUrl", () => {
  it("a public IPv4 address without a scheme defaults to https", () => {
    expect(normalizeServerUrl("203.0.113.5")).toBe("https://203.0.113.5");
    expect(normalizeServerUrl("203.0.113.5:3001")).toBe("https://203.0.113.5:3001");
    expect(normalizeServerUrl("8.8.8.8")).toBe("https://8.8.8.8");
  });

  it("each private range defaults to http", () => {
    expect(normalizeServerUrl("10.1.2.3:3001")).toBe("http://10.1.2.3:3001");
    expect(normalizeServerUrl("172.16.0.9")).toBe("http://172.16.0.9");
    expect(normalizeServerUrl("172.31.0.9:3001")).toBe("http://172.31.0.9:3001");
    expect(normalizeServerUrl("192.168.1.20:3001")).toBe("http://192.168.1.20:3001");
    expect(normalizeServerUrl("169.254.10.10")).toBe("http://169.254.10.10");
    expect(normalizeServerUrl("127.0.0.1:3001")).toBe("http://127.0.0.1:3001");
    expect(normalizeServerUrl("localhost:3001")).toBe("http://localhost:3001");
  });

  it("a Tailscale address (100.64.x) defaults to http", () => {
    expect(normalizeServerUrl("100.64.1.1:3001")).toBe("http://100.64.1.1:3001");
    expect(normalizeServerUrl("100.101.102.103")).toBe("http://100.101.102.103");
  });

  it("a dotted public name defaults to https", () => {
    expect(normalizeServerUrl("media.example.com")).toBe("https://media.example.com");
    expect(normalizeServerUrl("media.example.com/")).toBe("https://media.example.com");
  });

  it("a single-label name and a .local name default to http", () => {
    expect(normalizeServerUrl("mediabox")).toBe("http://mediabox");
    expect(normalizeServerUrl("mediabox:3001")).toBe("http://mediabox:3001");
    expect(normalizeServerUrl("mediabox.local:3001")).toBe("http://mediabox.local:3001");
  });

  it("IPv6 literals use the same rule", () => {
    expect(normalizeServerUrl("[::1]:3001")).toBe("http://[::1]:3001");
    expect(normalizeServerUrl("[fe80::1]:3001")).toBe("http://[fe80::1]:3001");
    expect(normalizeServerUrl("[2606:4700:4700::1111]")).toBe("https://[2606:4700:4700::1111]");
  });

  it("an explicit scheme is kept as typed (stamped addresses are unchanged)", () => {
    expect(normalizeServerUrl("http://203.0.113.5:3001")).toBe("http://203.0.113.5:3001");
    expect(normalizeServerUrl("https://192.168.1.20:3001")).toBe("https://192.168.1.20:3001");
    expect(normalizeServerUrl("HTTP://Media.Example.com/")).toBe("HTTP://Media.Example.com");
    expect(normalizeServerUrl("https://media.example.com///")).toBe("https://media.example.com");
  });

  it("blank stays blank and surrounding space is dropped", () => {
    expect(normalizeServerUrl("")).toBe("");
    expect(normalizeServerUrl("   ")).toBe("");
    expect(normalizeServerUrl("  192.168.1.20  ")).toBe("http://192.168.1.20");
  });
});

describe("isPublicCleartext", () => {
  it("an explicit http:// address to a public host needs a confirmation", () => {
    expect(isPublicCleartext("http://203.0.113.5:3001")).toBe(true);
    expect(isPublicCleartext("http://media.example.com")).toBe(true);
    expect(isPublicCleartext("HTTP://media.example.com/")).toBe(true);
    expect(isPublicCleartext("http://[2606:4700:4700::1111]/")).toBe(true);
  });

  it("http to a private host does not", () => {
    for (const url of [
      "http://192.168.1.20:3001",
      "http://10.0.0.5",
      "http://172.20.1.1",
      "http://169.254.1.1",
      "http://100.64.1.1:3001",
      "http://localhost:3001",
      "http://mediabox",
      "http://nas.local",
      "http://[::1]:3001",
    ]) {
      expect(isPublicCleartext(url)).toBe(false);
    }
  });

  it("https never does, and a bare address (not yet normalized) is not cleartext", () => {
    expect(isPublicCleartext("https://203.0.113.5")).toBe(false);
    expect(isPublicCleartext("https://media.example.com")).toBe(false);
    expect(isPublicCleartext("203.0.113.5")).toBe(false);
    expect(isPublicCleartext("")).toBe(false);
  });

  it("whatever normalizeServerUrl makes from a bare address never needs a confirmation", () => {
    for (const bare of ["203.0.113.5", "media.example.com", "192.168.1.20:3001", "mediabox", "100.64.1.1"]) {
      expect(isPublicCleartext(normalizeServerUrl(bare))).toBe(false);
    }
  });
});

describe("cleartextWarning", () => {
  it("names the address and says what is at risk", () => {
    const w = cleartextWarning("http://203.0.113.5:3001/");
    expect(w.message).toContain("http://203.0.113.5:3001");
    expect(w.message).toMatch(/password/);
    expect(w.message).toMatch(/https/);
    expect(w.title.length).toBeGreaterThan(0);
    expect(w.confirm).toBe("Use http anyway");
  });
});
