import * as Haptics from "expo-haptics";
import { Platform } from "react-native";

/** Light haptic tick for transport buttons. No-op on TV. */
export function tick(): void {
  if (Platform.isTV) return;
  void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
}
