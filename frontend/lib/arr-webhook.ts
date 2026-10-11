// Which address to show for the *arr webhook URLs. Radarr, Sonarr and Lidarr
// call this server, so the address has to be one they can reach. The address
// the admin is using right now is the first choice; a loopback one (localhost)
// only works when the *arr app runs on this same PC, so a home-network address
// from the server is offered ahead of it. Pure so node:test can cover it.

export type WebhookBase = { label: string; url: string };

export function isLoopbackOrigin(origin: string): boolean {
  try {
    const host = new URL(origin).hostname.replace(/^\[|\]$/g, "").toLowerCase();
    return host === "localhost" || host.endsWith(".localhost") || host === "::1" || /^127\./.test(host);
  } catch {
    return false;
  }
}

// The choices, best first, without duplicates. `current` is the browser's own
// origin ("" when unknown).
export function webhookBases(current: string, known: WebhookBase[]): WebhookBase[] {
  const out: WebhookBase[] = [];
  const add = (b: WebhookBase) => {
    const url = b.url.replace(/\/+$/, "");
    if (url && !out.some((x) => x.url === url)) out.push({ label: b.label, url });
  };
  const here: WebhookBase | null = current ? { label: "Address you are using now", url: current } : null;
  if (here && isLoopbackOrigin(here.url)) {
    known.forEach(add);
    add(here);
  } else {
    if (here) add(here);
    known.forEach(add);
  }
  return out;
}

export function webhookUrl(base: string, path: string): string {
  return `${base.replace(/\/+$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}
