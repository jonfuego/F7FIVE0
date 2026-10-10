// A small `x of y` progress bar shared by the folder scan block and the music
// videos scan block, so both scans look alike. The percent comes from
// scanPercent (0 when the total is not known yet, so the bar reads empty
// rather than full before counting finishes).

"use client";

export function ScanBar({ percent }: { percent: number }) {
  return (
    <div
      className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full bg-emerald-500 transition-[width] duration-500"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
