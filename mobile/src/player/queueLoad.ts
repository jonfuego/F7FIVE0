/** Start playing fast, then fill the queue.
 *
 * Signing up to 60 stream URLs before anything plays made Play feel dead. This
 * signs the tapped track alone, resets the queue, adds it and plays it. Only
 * then does it sign the tracks behind and ahead (in parallel) and add them
 * around the playing one: the ones ahead at the end, the ones behind in front
 * (the playing track keeps playing; its index shifts). A request that is no
 * longer current stops before its next queue change.
 *
 * Pure: every player call is injected, so the tests run without TrackPlayer. */

export interface QueueLoadDeps<Item, Entry> {
  /** The window of the list, in list order. */
  items: readonly Item[];
  /** Where the tapped item sits in `items`. */
  tappedIndex: number;
  /** Sign one item. Null when it cannot play (offline and not downloaded, or the sign failed). */
  sign: (item: Item) => Promise<Entry | null>;
  /** Empty the queue. Called once, after the first track is signed. */
  reset: () => Promise<void>;
  /** Add entries at the end, or at `insertAt` when given. */
  add: (entries: Entry[], insertAt?: number) => Promise<void>;
  skip: (index: number) => Promise<void>;
  play: () => Promise<void>;
  /** False once a newer play request has started. */
  isCurrent: () => boolean;
  /** Called right after play() resolves. */
  onStarted?: () => void;
}

export type QueueLoadResult = "loaded" | "empty" | "superseded";

export async function loadQueueInStages<Item, Entry>(deps: QueueLoadDeps<Item, Entry>): Promise<QueueLoadResult> {
  const { items, tappedIndex, sign, isCurrent } = deps;
  const first = Math.min(Math.max(0, tappedIndex), Math.max(0, items.length - 1));

  // The tapped track first. When it cannot play, the next one that can starts
  // instead (the old behavior for an offline queue).
  let anchor: Entry | null = null;
  let anchorAt = -1;
  for (let i = first; i < items.length; i += 1) {
    const entry = await sign(items[i]);
    if (!isCurrent()) return "superseded";
    if (entry) {
      anchor = entry;
      anchorAt = i;
      break;
    }
  }
  if (!anchor) return "empty";

  await deps.reset();
  if (!isCurrent()) return "superseded";
  await deps.add([anchor]);
  if (!isCurrent()) return "superseded";
  await deps.skip(0);
  if (!isCurrent()) return "superseded";
  await deps.play();
  deps.onStarted?.();

  // Fill the queue around the playing track.
  const [behind, ahead] = await Promise.all([
    signAll(items.slice(0, first), sign),
    signAll(items.slice(anchorAt + 1), sign),
  ]);
  if (!isCurrent()) return "superseded";
  if (ahead.length > 0) await deps.add(ahead);
  if (!isCurrent()) return "superseded";
  if (behind.length > 0) await deps.add(behind, 0);
  return "loaded";
}

async function signAll<Item, Entry>(items: readonly Item[], sign: (item: Item) => Promise<Entry | null>): Promise<Entry[]> {
  const signed = await Promise.all(items.map((item) => sign(item)));
  const out: Entry[] = [];
  for (const e of signed) if (e !== null) out.push(e as Entry);
  return out;
}
