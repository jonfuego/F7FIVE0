// Admin: what podcast downloads use, the free space on each podcasts folder's
// drive, and the warning. There is no cap on downloads; the server raises
// `low_space` when free space drops below PODCAST_FREE_SPACE_WARN_GB (10 by
// default). GET /api/admin/podcasts/storage.
//
// Pure, so node:test covers it (podcast-storage.test.ts).

export type PodcastStorageFolder = {
  path: string;
  reachable: boolean;
  free_bytes: number | null;
  total_bytes: number | null;
};

export type PodcastStorage = {
  used_bytes: number;
  warn_gb: number;
  low_space: boolean;
  folders: PodcastStorageFolder[];
};

const GB = 1024 ** 3;

function gb(bytes: number): string {
  return (bytes / GB).toFixed(1);
}

/** The red line when free space is low: the drive with the least room. */
export function storageWarning(storage: PodcastStorage): string | null {
  if (!storage.low_space) return null;
  const open = storage.folders.filter((f) => f.reachable && f.free_bytes != null);
  if (open.length === 0) return null;
  const tightest = open.reduce((a, b) => ((a.free_bytes as number) <= (b.free_bytes as number) ? a : b));
  return (
    `Podcast storage is low: ${tightest.path} has ${gb(tightest.free_bytes as number)} GB free ` +
    `(the warning starts below ${storage.warn_gb} GB).`
  );
}

/** One line under the podcasts folders: what the downloads use and the room left. */
export function storageSummary(storage: PodcastStorage): string {
  if (storage.folders.length === 0) return "No podcasts folder yet.";
  const parts = storage.folders.map((f) =>
    f.reachable && f.free_bytes != null && f.total_bytes != null
      ? `${f.path}: ${gb(f.free_bytes)} GB free of ${gb(f.total_bytes)} GB.`
      : `${f.path}: not reachable.`,
  );
  return `${gb(storage.used_bytes)} GB downloaded. ${parts.join(" ")}`;
}
