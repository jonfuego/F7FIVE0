"use client";

// F7FIVE0 wordmark with the Hidden HIVE easter egg.
// Tap the logo 7 times (each tap within 600 ms of the last) and the black letters
// step back while the red layer closes up into a properly kerned HIVE, then it
// all snaps back. About 2.4 s, silent. Styles: f7five0_hive-wordmark_v1.css.
//
// Geometry: traced from design/F7FIVE0_Logo.psd (see design/logos/f7five0-wordmark.svg),
// split into its pieces. Units are the 1476 x 298 viewBox.
//   - H right stem slides 40 units left to meet the crossbar.
//   - I slides 13 units left for even spacing between H and V.
//
// Note: the wordmark is usually a link to "/". On other pages the first tap
// navigates home as normal, so the egg effectively lives on the home page.

import Link from "next/link";
import { useCallback, useRef, useState, type MouseEvent } from "react";

const P: Record<string, string> = {
  "h-left": "M4920 1535 l0 -1445 150 0 150 0 0 620 0 620 630 0 630 0 0 250 0 250 -630 0 -630 0 0 575 0 575 -150 0 -150 0 0 -1445z",
  "h-right": "M6880 1535 l0 -1445 105 0 105 0 0 1445 0 1445 -105 0 -105 0 0 -1445z",
  "i": "M7250 1535 l0 -1445 110 0 110 0 0 1445 0 1445 -110 0 -110 0 0 -1445z",
  "v": "M8027 2973 l91 -4 7 -17 c4 -9 198 -582 431 -1272 234 -690 429 -1258 433 -1263 4 -4 173 518 376 1160 203 643 385 1221 406 1286 l37 117 -97 0 -97 0 -314 -1085 c-172 -597 -315 -1083 -317 -1081 -2 1 -147 489 -322 1082 l-318 1079 -204 1 c-112 0 -163 -1 -112 -3z",
  "e": "M10570 1540 l0 -1250 845 0 845 0 0 145 0 145 -740 0 -740 0 0 375 0 375 748 2 c411 1 705 4 655 5 l-93 4 0 244 0 245 -655 0 -655 0 0 328 0 327 745 -4 745 -3 0 156 0 156 -850 0 -850 0 0 -1250z",
  "black": "M0 1535 l0 -1445 300 0 300 0 0 620 0 620 630 0 630 0 0 250 0 250 -630 0 -630 0 0 325 0 325 715 0 715 0 0 250 0 250 -1015 0 -1015 0 0 -1445z M4610 1535 l0 -1445 155 0 155 0 0 1445 0 1445 -155 0 -155 0 0 -1445z M5220 2730 l0 -250 715 0 715 0 0 250 0 250 -715 0 -715 0 0 -250z M7090 1535 l0 -1445 80 0 80 0 0 1445 0 1445 -80 0 -80 0 0 -1445z M8006 2204 c144 -429 363 -1078 487 -1444 l224 -665 253 0 253 0 487 1420 c268 781 490 1430 494 1443 l7 22 -202 -2 -203 -3 -405 -1282 c-222 -705 -407 -1280 -411 -1278 -4 2 -199 573 -435 1268 -235 696 -430 1269 -434 1275 -3 6 -85 13 -192 17 l-186 8 263 -779z M10380 1535 l0 -1445 1040 0 1040 0 0 245 0 245 -100 0 -100 0 0 -145 0 -145 -845 0 -845 0 0 1250 0 1250 850 0 850 0 0 -155 0 -155 100 0 100 0 0 250 0 250 -1045 0 -1045 0 0 -1445z M13687 2949 c-337 -36 -612 -245 -736 -561 -86 -219 -122 -485 -122 -914 0 -870 216 -1316 701 -1446 l85 -22 180 0 180 1 80 22 c379 103 589 398 670 939 50 336 35 920 -31 1212 -81 359 -258 588 -548 709 -126 52 -309 76 -459 60z m260 -474 c125 -62 193 -216 235 -535 17 -129 17 -767 0 -915 -30 -261 -64 -364 -150 -450 -80 -79 -183 -111 -305 -94 -175 24 -270 168 -318 483 -26 170 -37 624 -20 846 33 444 116 633 302 685 79 22 186 14 256 -20z M2240 2650 l0 -250 701 0 700 0 -49 -57 c-115 -133 -334 -456 -471 -695 -141 -246 -267 -570 -347 -892 -34 -138 -96 -478 -110 -604 l-7 -62 279 2 279 3 3 40 c1 22 9 105 18 185 79 730 359 1363 901 2038 l83 103 0 219 0 220 -990 0 -990 0 0 -250z M10780 2160 l0 -330 100 0 100 0 0 330 0 330 -100 0 -100 0 0 -330z M12090 1585 l0 -245 90 0 90 0 0 245 0 245 -90 0 -90 0 0 -245z M10780 955 l0 -375 100 0 100 0 0 375 0 375 -100 0 -100 0 0 -375z"
};
const T = "translate(0 298) scale(0.1 -0.1)";
const TAPS = 7;
const WINDOW_MS = 600;
const DURATION_MS = 2400;

type Props = {
  href?: string;
  height?: number;                       // rendered height in px (default 28)
  plate?: "auto" | "always" | "never";   // white plate off white grounds, per the brand rules
  className?: string;
  onEasterEgg?: () => void;              // hook for the custom sound later
};

export function HiveWordmark({ href = "/", height = 28, plate = "auto", className, onEasterEgg }: Props) {
  const taps = useRef<{ n: number; last: number }>({ n: 0, last: 0 });
  const [run, setRun] = useState(0);     // increments to restart the animation
  const [playing, setPlaying] = useState(false);

  const onClick = useCallback((e: MouseEvent) => {
    const now = performance.now();
    const t = taps.current;
    t.n = now - t.last <= WINDOW_MS ? t.n + 1 : 1;
    t.last = now;
    if (t.n > 1) e.preventDefault();     // taps 2..7 never navigate
    if (t.n >= TAPS && !playing) {
      t.n = 0;
      setRun((r) => r + 1);
      setPlaying(true);
      onEasterEgg?.();
      window.setTimeout(() => setPlaying(false), DURATION_MS);
    }
  }, [playing, onEasterEgg]);

  const pad = Math.round(height * 0.25);
  return (
    <Link
      href={href}
      onClick={onClick}
      aria-label="F7FIVE0"
      className={["f7-hive", `f7-hive-plate-${plate}`, className].filter(Boolean).join(" ")}
      style={{ ["--f7-hive-pad" as string]: `${pad}px` }}
    >
      <svg
        key={run}
        className={playing ? "f7-hive-svg is-playing" : "f7-hive-svg"}
        viewBox="0 0 1476 298"
        height={height}
        width={(height * 1476) / 298}
        aria-hidden="true"
      >
        <g className="f7-hive-red">
          <g><path transform={T} d={P["h-left"]} /></g>
          <g className="f7-hive-hr"><path transform={T} d={P["h-right"]} /></g>
          <g className="f7-hive-i"><path transform={T} d={P["i"]} /></g>
          <g><path transform={T} d={P["v"]} /></g>
          <g><path transform={T} d={P["e"]} /></g>
        </g>
        <g className="f7-hive-black"><path transform={T} d={P["black"]} /></g>
      </svg>
    </Link>
  );
}

export default HiveWordmark;
