import { QueryClient } from "@tanstack/react-query";

/** In-memory only (no persistent HTTP cache that could go stale across
 * releases; spec 6.5). */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

/** Refresh everything that depends on watch state (Home On Deck + Continue
 * Watching, per-file progress, show/movie watched checks) after a mark
 * watched/unwatched or when the player closes. */
export function invalidateWatchState(): void {
  for (const key of ["on-deck", "continue", "progress-all", "progress"]) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}
