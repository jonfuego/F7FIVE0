// /admin/audio-analysis

"use client";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AudioAnalysisSection } from "../AudioAnalysisSection";

export default function AudioAnalysisPage() {
  return (
    <>
      <AdminPageHeader title="Audio analysis">
        Loudness leveling, the waveform scrubber and similar-track radio.
      </AdminPageHeader>
      <AudioAnalysisSection />
    </>
  );
}
