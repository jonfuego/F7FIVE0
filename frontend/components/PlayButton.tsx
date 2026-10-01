// Play link. Routes to /watch/<media_file_id>, which Slice 4 will implement
// as the hls.js + native-fallback player page. Rendered as a styled link so
// right-click "open in new tab" works and prefetching kicks in.

import Link from "next/link";

type Props = {
  mediaFileId: string;
  label?: string;
  size?: "sm" | "md";
  variant?: "primary" | "secondary";
};

export function PlayButton({
  mediaFileId,
  label = "Play",
  size = "md",
  variant = "primary",
}: Props) {
  const sizeClass =
    size === "sm"
      ? "px-3 py-1 text-xs"
      : "px-4 py-2 text-sm";
  const variantClass =
    variant === "primary"
      ? "bg-amber-500 text-neutral-950 hover:bg-amber-400"
      : "border border-neutral-700 text-neutral-100 hover:border-neutral-500 hover:text-white";
  return (
    <Link
      href={`/watch/${mediaFileId}`}
      className={`inline-flex items-center gap-1.5 rounded-md font-medium transition ${sizeClass} ${variantClass}`}
    >
      <PlayIcon size={size === "sm" ? 12 : 14} />
      {label}
    </Link>
  );
}

function PlayIcon({ size }: { size: number }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
    >
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}
