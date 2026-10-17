/** Latest tap wins. Each play request takes a token; once a newer request takes
 * one, the older token is stale and its request stops before its next queue
 * change. Pure so it can be tested without the player. */

export interface PlayToken {
  readonly id: number;
  /** True while no newer request has taken a token. */
  isCurrent(): boolean;
}

export interface PlayTokenSource {
  take(): PlayToken;
}

export function createPlayTokenSource(): PlayTokenSource {
  let latest = 0;
  return {
    take(): PlayToken {
      latest += 1;
      const id = latest;
      return { id, isCurrent: () => id === latest };
    },
  };
}
