import { useRouter, type Href } from "expo-router";
import { ArrowLeft } from "lucide-react-native";
import React from "react";

import { IconButton } from "./IconButton";

interface BackButtonProps {
  /** Where to go when the screen was opened with no history (a deep link):
   * the screen's own tab, such as "/music", "/movies" or "/podcasts". */
  fallback: Href;
}

/** Back for a detail screen, used as the Screen's `right`. The hardware and
 * gesture back are expo-router's own; this is the on-screen one. It is an
 * IconButton, so the touch target is 44 dp or more. */
export function BackButton({ fallback }: BackButtonProps): React.ReactElement {
  const router = useRouter();
  const back = () => (router.canGoBack() ? router.back() : router.replace(fallback));
  return <IconButton icon={ArrowLeft} accessibilityLabel="Back" onPress={back} />;
}
