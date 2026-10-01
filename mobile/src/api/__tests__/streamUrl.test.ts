import { playWithUrlRecovery, SignedStream } from "../streamUrl";

const STREAM: SignedStream = { url: "http://x/stream/direct/1?sig=a", mode: "direct" };
const FRESH: SignedStream = { url: "http://x/stream/direct/1?sig=b", mode: "direct" };

describe("expired-URL recovery", () => {
  it("plays on the first signed URL when it works", async () => {
    const getUrl = jest.fn(async () => STREAM);
    const tryPlay = jest.fn(async () => "ok");
    const result = await playWithUrlRecovery(getUrl, tryPlay);
    expect(result).toBe("ok");
    expect(getUrl).toHaveBeenCalledTimes(1);
    expect(tryPlay).toHaveBeenCalledTimes(1);
  });

  it("re-signs and retries exactly once on a load error, then succeeds", async () => {
    const getUrl = jest
      .fn<Promise<SignedStream>, []>()
      .mockResolvedValueOnce(STREAM)
      .mockResolvedValueOnce(FRESH);
    const tryPlay = jest
      .fn<Promise<string>, [SignedStream]>()
      .mockRejectedValueOnce(new Error("403 expired"))
      .mockResolvedValueOnce("ok");
    const result = await playWithUrlRecovery(getUrl, tryPlay);
    expect(result).toBe("ok");
    expect(getUrl).toHaveBeenCalledTimes(2);
    expect(tryPlay).toHaveBeenCalledTimes(2);
    expect(tryPlay).toHaveBeenLastCalledWith(FRESH);
  });

  it("retries only once: a second failure propagates", async () => {
    const getUrl = jest.fn(async () => STREAM);
    const tryPlay = jest.fn(async () => {
      throw new Error("still failing");
    });
    await expect(playWithUrlRecovery(getUrl, tryPlay)).rejects.toThrow("still failing");
    expect(getUrl).toHaveBeenCalledTimes(2);
    expect(tryPlay).toHaveBeenCalledTimes(2);
  });

  it("surfaces the original error if re-signing itself fails", async () => {
    const getUrl = jest
      .fn<Promise<SignedStream>, []>()
      .mockResolvedValueOnce(STREAM)
      .mockRejectedValueOnce(new Error("resign failed"));
    const tryPlay = jest.fn(async () => {
      throw new Error("original play error");
    });
    await expect(playWithUrlRecovery(getUrl, tryPlay)).rejects.toThrow("original play error");
    expect(tryPlay).toHaveBeenCalledTimes(1);
  });
});
