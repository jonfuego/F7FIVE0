// Android TV stub for the player 3-dot menu. Metro resolves this (.tv.tsx)
// instead of PlayerTrackMenu.tsx when EXPO_TV=1 (see metro.config.js), so the
// TV bundle never pulls in the menu, its router push, or the album / artist
// loaders. Same pattern as CastButton.tv.tsx. There is no overflow menu on the
// 10-foot UI, so this renders nothing.

import React from "react";

export interface PlayerTrackMenuProps {
  albumId: string | null;
  artistId: string | null;
  beforeNavigate?: () => void;
  size?: number;
  color?: string;
}

export function PlayerTrackMenu(_props: PlayerTrackMenuProps): React.ReactElement | null {
  return null;
}
