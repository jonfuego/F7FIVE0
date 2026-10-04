import { chooseServer, parseStamp } from "@/lib/serverStamp";

describe("parseStamp", () => {
  it("returns origins in order", () => {
    expect(
      parseStamp('{"v":1,"servers":["https://media.example.com","http://192.168.1.20:3001"]}'),
    ).toEqual(["https://media.example.com", "http://192.168.1.20:3001"]);
  });

  it("drops junk, paths, duplicates and non-http schemes", () => {
    expect(
      parseStamp(
        JSON.stringify({
          servers: [
            "HTTPS://media.example.com/",
            "https://media.example.com",
            "ftp://x",
            "https://a.example.com/path",
            42,
            "javascript:alert(1)",
            "http://10.0.0.2:3001",
          ],
        }),
      ),
    ).toEqual(["https://media.example.com", "http://10.0.0.2:3001"]);
  });

  it("is empty for missing or malformed stamps", () => {
    expect(parseStamp(null)).toEqual([]);
    expect(parseStamp("")).toEqual([]);
    expect(parseStamp("not json")).toEqual([]);
    expect(parseStamp('{"servers":"https://x"}')).toEqual([]);
    expect(parseStamp("[1,2]")).toEqual([]);
  });
});

describe("chooseServer", () => {
  const up = (alive: string[]) => async (s: string) => alive.includes(s);

  it("prefers the earliest address that answers", async () => {
    const list = ["https://public", "http://home"];
    expect(await chooseServer(list, up(["https://public", "http://home"]))).toBe("https://public");
    expect(await chooseServer(list, up(["http://home"]))).toBe("http://home");
  });

  it("falls back to the first address when nothing answers", async () => {
    expect(await chooseServer(["https://public", "http://home"], up([]))).toBe("https://public");
  });

  it("treats a probe that throws as down", async () => {
    const probe = async (s: string) => {
      if (s === "https://public") throw new Error("boom");
      return true;
    };
    expect(await chooseServer(["https://public", "http://home"], probe)).toBe("http://home");
  });

  it("is empty with no addresses", async () => {
    expect(await chooseServer([], up([]))).toBe("");
  });
});
