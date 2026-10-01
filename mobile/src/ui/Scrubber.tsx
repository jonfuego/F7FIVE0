import React, { useRef, useState } from "react";
import { LayoutChangeEvent, PanResponder, StyleSheet, View } from "react-native";

import { colors, radius } from "@/state/theme";

interface ScrubberProps {
  position: number;
  duration: number;
  onSeek: (sec: number) => void;
}

/** Minimal drag/tap scrubber built on PanResponder (no extra deps). While
 * dragging it shows the dragged position; on release it seeks. */
export function Scrubber({ position, duration, onSeek }: ScrubberProps): React.ReactElement {
  const [width, setWidth] = useState(0);
  const [dragFrac, setDragFrac] = useState<number | null>(null);
  const widthRef = useRef(0);
  const durationRef = useRef(duration);
  durationRef.current = duration;

  const onLayout = (e: LayoutChangeEvent) => {
    const w = e.nativeEvent.layout.width;
    setWidth(w);
    widthRef.current = w;
  };

  const responder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderMove: (evt) => {
        const w = widthRef.current || 1;
        const frac = Math.min(Math.max(evt.nativeEvent.locationX / w, 0), 1);
        setDragFrac(frac);
      },
      onPanResponderRelease: (evt) => {
        const w = widthRef.current || 1;
        const frac = Math.min(Math.max(evt.nativeEvent.locationX / w, 0), 1);
        setDragFrac(null);
        onSeek(frac * (durationRef.current || 0));
      },
    }),
  ).current;

  const frac =
    dragFrac !== null ? dragFrac : duration > 0 ? Math.min(position / duration, 1) : 0;
  const filled = Math.round(frac * width);

  return (
    <View
      style={styles.hit}
      onLayout={onLayout}
      accessibilityRole="adjustable"
      accessibilityLabel="Seek"
      {...responder.panHandlers}
    >
      <View style={styles.track}>
        <View style={[styles.fill, { width: filled }]} />
        <View style={[styles.thumb, { left: Math.max(filled - 7, 0) }]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  hit: { paddingVertical: 12, marginTop: 12 },
  track: { height: 4, backgroundColor: colors.surfaceAlt, borderRadius: radius.pill, justifyContent: "center" },
  fill: { position: "absolute", height: 4, backgroundColor: colors.accent, borderRadius: radius.pill },
  thumb: {
    position: "absolute",
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.accent,
  },
});
