// F7FIVE0 wordmark with the Hidden HIVE easter egg (React Native, mobile).
// Tap the logo 7 times (each tap within 600 ms of the last): the black letters step
// back and fade, the red layer closes up into a properly kerned HIVE, then it all
// snaps back. About 2.4 s, silent. No new dependencies: core Animated + Image layers.
//
// Assets: ./hive-egg/*.png, one transparent full-canvas layer per piece at 2x
// (2952 x 596, canvas units 1476 x 298). Traced from design/F7FIVE0_Logo.psd.
//   - H right stem slides 40 canvas units left to meet the crossbar.
//   - I slides 13 canvas units left for even spacing between H and V.

import { useCallback, useRef } from "react";
import { AccessibilityInfo, Animated, Easing, Image, Pressable, View } from "react-native";

const CANVAS_W = 1476;
const CANVAS_H = 298;
const TAPS = 7;
const WINDOW_MS = 600;

const SRC = {
  hLeft: require("./hive-egg/h-left.png"),
  hRight: require("./hive-egg/h-right.png"),
  i: require("./hive-egg/i.png"),
  v: require("./hive-egg/v.png"),
  e: require("./hive-egg/e.png"),
  black: require("./hive-egg/black.png"),
};

type Props = {
  height?: number;            // rendered height in dp (default 28)
  plate?: boolean;            // white plate; true on any non-white ground (always on dark)
  onPress?: () => void;       // normal tap action (e.g. go home), fires on the first tap only
  onEasterEgg?: () => void;   // hook for the custom sound later
};

export function HiveWordmark({ height = 28, plate = true, onPress, onEasterEgg }: Props) {
  const width = (height * CANVAS_W) / CANVAS_H;
  const u = width / CANVAS_W; // dp per canvas unit
  const blackOpacity = useRef(new Animated.Value(1)).current;
  const blackX = useRef(new Animated.Value(0)).current;
  const hrX = useRef(new Animated.Value(0)).current;
  const iX = useRef(new Animated.Value(0)).current;
  const taps = useRef({ n: 0, last: 0, playing: false }).current;

  const play = useCallback(async () => {
    taps.playing = true;
    onEasterEgg?.();
    const reduce = await AccessibilityInfo.isReduceMotionEnabled();
    const out = Easing.bezier(0.2, 0.7, 0.2, 1);
    const back = Easing.bezier(0.5, 0, 0.75, 0);
    const t = (v: Animated.Value, to: number, ms: number, easing: (x: number) => number, delay = 0) =>
      Animated.timing(v, { toValue: to, duration: reduce && v !== blackOpacity ? 0 : ms, delay, easing, useNativeDriver: true });
    Animated.sequence([
      Animated.parallel([
        t(blackOpacity, 0, 300, out),
        t(blackX, reduce ? 0 : -10 * u, 300, out),
        t(hrX, -40 * u, 450, out, 240),
        t(iX, -13 * u, 410, out, 290),
      ]),
      Animated.delay(900),
      Animated.parallel([t(hrX, 0, 340, back), t(iX, 0, 340, back)]),
      Animated.parallel([t(blackOpacity, 1, 450, back), t(blackX, 0, 450, back)]),
    ]).start(() => { taps.playing = false; });
  }, [blackOpacity, blackX, hrX, iX, u, onEasterEgg, taps]);

  const handlePress = useCallback(() => {
    const now = Date.now();
    taps.n = now - taps.last <= WINDOW_MS ? taps.n + 1 : 1;
    taps.last = now;
    if (taps.n === 1) onPress?.();
    if (taps.n >= TAPS && !taps.playing) { taps.n = 0; play(); }
  }, [onPress, play, taps]);

  const layer = { position: "absolute" as const, left: 0, top: 0, width, height };
  const pad = Math.round(height * 0.25);
  return (
    <Pressable onPress={handlePress} accessibilityRole="button" accessibilityLabel="F7FIVE0" hitSlop={8}>
      <View style={[plate && { backgroundColor: "#FFFFFF", padding: pad }]}>
        <View style={{ width, height }}>
          <Image source={SRC.hLeft} style={layer} />
          <Animated.Image source={SRC.hRight} style={[layer, { transform: [{ translateX: hrX }] }]} />
          <Animated.Image source={SRC.i} style={[layer, { transform: [{ translateX: iX }] }]} />
          <Image source={SRC.v} style={layer} />
          <Image source={SRC.e} style={layer} />
          <Animated.Image source={SRC.black} style={[layer, { opacity: blackOpacity, transform: [{ translateX: blackX }] }]} />
        </View>
      </View>
    </Pressable>
  );
}

export default HiveWordmark;
