# Hidden HIVE easter egg v1

Tap the wordmark 7 times, each tap within 600 ms of the last. The black letters step back and fade, the red layer closes up into a properly kerned HIVE, it holds, then everything snaps back. About 2.4 s. Silent for now: both components expose an `onEasterEgg` callback for the sound later.

## Motion

| Time | What moves |
|---|---|
| 0 to 0.3 s | Black layer fades out and steps back 10 units left |
| 0.24 to 0.7 s | H right stem slides 40 units left to meet the crossbar; I slides 13 units left |
| 0.7 to 1.6 s | HIVE holds |
| 1.6 to 1.95 s | H right stem and I return |
| 1.95 to 2.4 s | Black layer fades back in and snaps into place |

Units are the wordmark's 1476 x 298 canvas. V and E don't move. Reduced motion: nothing slides; the pieces jump while the black is faded out.

## Files

| File | For |
|---|---|
| `f7five0_hive-egg-preview_v1.html` | Open in a browser to try it (tap the logo 7 times, or Play now; toggle dark) |
| `web/f7five0_hive-wordmark_v1.tsx` | Next.js client component `HiveWordmark` (inline SVG, wraps `next/link`) |
| `web/f7five0_hive-wordmark_v1.css` | Its styles and keyframes; import once from `app/globals.css` |
| `mobile/f7five0_hive-wordmark_v1.tsx` | React Native component `HiveWordmark` (core Animated + Image layers, no new dependency) |
| `mobile/hive-egg/*.png` | Its layers: one transparent 2x full-canvas PNG per piece |

Not wired into `frontend/` or `mobile/` yet. To use: web, copy the component and CSS into `frontend/components/` and swap it in for `Wordmark`. Mobile, copy the component and the `hive-egg/` folder into `mobile/src/ui/` and swap it in for `Wordmark`.

On web the wordmark links to `/`, so on other pages the first tap navigates home as normal and the egg effectively lives on the home page. On mobile the first tap fires `onPress`; taps 2 to 7 only count toward the egg.

Pieces are traced from `design/F7FIVE0_Logo.psd`, the same source as `logos/f7five0-wordmark.svg`.
