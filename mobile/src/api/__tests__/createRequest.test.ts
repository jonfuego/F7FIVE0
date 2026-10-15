import { ApiClient, ApiError } from "../client";
import { createRequest, requestErrorDetail } from "../media";
import type { TokenStore } from "../tokenStore";

jest.mock("@/state/config", () => ({ getApiBase: () => "http://x" }));

const store: TokenStore = {
  async getRefresh() {
    return "refresh";
  },
  async setRefresh() {},
  async clear() {},
};

function reply(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() {
      return body;
    },
  } as unknown as Response;
}

function clientAnswering(status: number, body: unknown) {
  const fetchImpl = jest.fn(async () => reply(status, body));
  const api = new ApiClient({ baseUrl: "http://x", tokenStore: store, fetchImpl: fetchImpl as unknown as typeof fetch });
  return { api, fetchImpl };
}

const HIT = { kind: "series", external_id: "81189", title: "Breaking Bad", year: 2008, poster_url: "http://img/p.jpg" };

describe("createRequest", () => {
  it("sends title, year and poster_url with kind and external_id", async () => {
    const { api, fetchImpl } = clientAnswering(201, { id: "r1" });
    await createRequest(api, HIT);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://x/api/requests");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      kind: "series",
      external_id: "81189",
      title: "Breaking Bad",
      year: 2008,
      poster_url: "http://img/p.jpg",
    });
  });

  it("falls back to the chosen kind when the hit has none", async () => {
    const { api, fetchImpl } = clientAnswering(201, {});
    await createRequest(api, { ...HIT, kind: "" }, "movie");
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(init.body as string).kind).toBe("movie");
  });

  it("rejects on a 422 instead of reporting success", async () => {
    const { api } = clientAnswering(422, { detail: [{ loc: ["body", "title"], msg: "Field required" }] });
    await expect(createRequest(api, HIT)).rejects.toMatchObject({ name: "ApiError", status: 422 });
  });

  it("rejects with the server detail on a 409", async () => {
    const { api } = clientAnswering(409, { detail: "already_requested" });
    const err = await createRequest(api, HIT).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(requestErrorDetail(err)).toBe("already_requested");
  });
});

describe("requestErrorDetail", () => {
  it("is undefined when the error has no string detail", () => {
    expect(requestErrorDetail(new Error("x"))).toBeUndefined();
    expect(requestErrorDetail(new ApiError(422, "x", { detail: [{ msg: "m" }] }))).toBeUndefined();
    expect(requestErrorDetail(null)).toBeUndefined();
  });
});
