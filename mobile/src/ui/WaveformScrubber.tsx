import React, { useMemo, useRef, useState } from "react";
import { LayoutChangeEvent, PanResponder, StyleSheet, View } from "react-native";

import { colors, radius } from "@/state/theme";
import { bucketPeaks, isBarPlayed, peakToHeight } from "@/player/waveform";
import { Scrubber } from "./Scrubber";

interface WaveformScrubberProps {
  /** Precomputed peaks 0..100 from GET /api/tracks/{id}/waveform. */
  peaks?: number[] | null;
  position: number;
  duration: number;
  onSeek: (sec: number) => void;
}

/** Number of bars to render. We downsample the peaks to this many buckets so a
 * high-resolution waveform still draws cheaply as plain Views (no SVG/native
 * dep, keeps the current prebuild). */
const BAR_COUNT = 64;
const MIN_BAR = 2;
const MAX_BAR = 40;

/** Waveform scrubber for the full-screen player (crit 49). Renders precomputed
 * peaks as bars; the played portion is tinted with the accent and the rest is
 * dimmed. Tap/drag seeks. Falls back to the plain Scrubber when there are no
 * peaks (backend hasn't analysed the track yet). */
export function WaveformScrubber({ peaks, position, duration, onSeek }: WaveformScrubberProps): React.ReactElement {
  const [width, setWidth] = useState(0);
  const [dragFrac, setDragFrac] = useState<number | null>(null);
  const widthRef = useRef(0);
  const durationRef = useRef(duration);
  durationRef.current = duration;

  const bars = useMemo(() => (peaks && peaks.length > 0 ? bucketPeaks(peaks, BAR_COUNT) : []), [peaks]);

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
        setDragFrac(Math.min(Math.max(evt.nativeEvent.locationX / w, 0), 1));
      },
      onPanResponderRelease: (evt) => {
        const w = widthRef.current || 1;
        const frac = Math.min(Math.max(evt.nativeEvent.locationX / w, 0), 1);
        setDragFrac(null);
        onSeek(frac * (durationRef.current || 0));
      },
    }),
  ).current;

  // No peaks yet -> the existing plain scrubber (identical seek behaviour).
  if (bars.length === 0) {
    return <Scrubber position={position} duration={duration} onSeek={onSeek} />;
  }

  const frac = dragFrac !== null ? dragFrac : duration > 0 ? Math.min(position / duration, 1) : 0;

  return (
    <View
      style={styles.hit}
      onLayout={onLayout}
      accessibilityRole="adjustable"
      accessibilityLabel="Seek waveform"
      {...responder.panHandlers}
    >
      <View style={styles.row}>
        {bars.map((p, i) => {
          const h = peakToHeight(p, MIN_BAR, MAX_BAR);
          const played = isBarPlayed(i, bars.length, frac);
          return (
            <View
              key={i}
              style={[styles.bar, { height: h, backgroundColor: played ? colors.accent : colors.surfaceHi }]}
            />
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  hit: { paddingVertical: 12, marginTop: 12 },
  row: { flexDirection: "row", alignItems: "center", height: MAX_BAR, gap: 2 },
  bar: { flex: 1, borderRadius: radius.pill, minHeight: MIN_BAR },
});
