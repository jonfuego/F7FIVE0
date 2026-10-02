// TV stub for the cast button. The TV build has no cast sender, so this renders
// nothing. Metro resolves this .tv.tsx ahead of CastButton.tsx for TV, keeping
// react-native-google-cast out of the TV bundle entirely.
import React from "react";

export function CastButton(_props: {
  size?: number;
  tintColor?: string;
}): React.ReactElement | null {
  return null;
}
