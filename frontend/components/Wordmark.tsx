// The F7FIVE0 wordmark: "F7" in the serif face, "FIVE0" in the display
// face. Used in the top bar, login page, and anywhere else the brand
// shows. Style rules live in globals.css under .marquee-logo so the
// wordmark renders identically inside the top bar and anywhere else
// it shows.

import Link from "next/link";

type Props = {
  href?: string;
};

export function Wordmark({ href = "/" }: Props) {
  return (
    <Link href={href} className="marquee-logo" aria-label="F7FIVE0">
      <span className="wm-lead">F7</span>
      <span className="wm-tail">FIVE0</span>
    </Link>
  );
}
