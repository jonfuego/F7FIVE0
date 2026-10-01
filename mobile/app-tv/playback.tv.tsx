import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";
import { View } from "react-native";

import { useProgress } from "@/api/queries";
import { invalidateWatchState } from "@/state/query";
import { QueryState } from "@/ui/QueryState";
import { resumePointFor } from "@/video/transport";
import { VideoPlayer } from "@/video/VideoPlayer";

/** TV playback: full-screen video driven by the remote. The shared player's
 * transport (back 10 / play-pause / forward 30, scrubber, Skip intro, Up Next)
 * is made of focusable Pressables, so the D-pad moves between them and Select
 * activates. Resumes saved progress like the phone and auto-advances episodes. */
export default function TvPlayback(): React.ReactElement {
  const { id, resume } = useLocalSearchParams<{ id: string; resume?: string }>();
  const router = useRouter();
  const explicit = resume != null && resume !== "" ? parseInt(resume, 10) || 0 : null;
  const progress = useProgress(explicit == null ? id ?? "" : "");
  const waiting = explicit == null && !!id && progress.isLoading;
  const resumeSec = explicit ?? resumePointFor(progress.data);
  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <QueryState isLoading={waiting} isError={!id} data={id ? { id } : undefined} onRetry={() => router.back()}>
        {(data) => (
          <VideoPlayer
            key={data.id}
            mediaFileId={data.id}
            resumeSec={resumeSec}
            onClose={() => {
              invalidateWatchState();
              router.back();
            }}
            onPlayNext={(nextId) => router.replace(`/watch/${nextId}`)}
          />
        )}
      </QueryState>
    </View>
  );
}
