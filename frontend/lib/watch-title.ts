// Title shown in the watch page's top bar (/watch/<mediaFileId>).
//
// Pure (no React, no "@/" imports) so node:test can cover it.
//
// The dock queue (localStorage f7five0.queue.v1) holds MUSIC. Its current item
// is only a valid title source when it is the very file this page is showing
// (the dock-linked audio view). For a movie or episode opened while a song is
// queued, the queue item is unrelated: falling back to it showed the song's
// title over the movie while the resume prompt was up and the stream was still
// loading (and for good if the stream came back without a title).

export interface WatchTitleInput {
  /** The route's media file id. */
  mediaFileId: string | null | undefined;
  /** Title from /api/stream/start for this file, once it has loaded. */
  streamTitle: string | null | undefined;
  /** The dock queue's current item, if any. */
  queueCurrent: { media_file_id: string; title: string } | null | undefined;
  /** True while the page is following the dock (linked view or catching up). */
  useDockAudio: boolean;
}

export const WATCH_TITLE_LOADING = "Loading…";

export function watchTitle(input: WatchTitleInput): string {
  const streamTitle = input.streamTitle?.trim();
  if (streamTitle) return streamTitle;
  const q = input.queueCurrent;
  if (q && q.title && (input.useDockAudio || q.media_file_id === input.mediaFileId)) {
    return q.title;
  }
  return WATCH_TITLE_LOADING;
}
