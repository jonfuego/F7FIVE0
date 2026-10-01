import { useLocalSearchParams, useRouter } from "expo-router";
import React from "react";
import { StatusBar } from "expo-status-bar";
import { View } from "react-native";

import { useProgress } from "@/api/queries";
import { resumePointFor } from "@/video/transport";
import { VideoPlayer } from "@/video/VideoPlayer";
import { invalidateWatchState } from "@/state/query";
import { QueryState } from "@/ui/QueryState";

/** Full-screen video player route. `id` is the media file id to play. `resume`
 * is an explicit start position in seconds (`resume=0` = from the beginning);
 * without it the saved progress is used, like Plex (Continue Watching, On Deck,
 * episode rows and Up Next all resume where you left off). Up Next replaces
 * this route with the next episode's media file (keyed so the player remounts). */
export default function WatchScreen(): React.ReactElement {
  const { id, resume } = useLocalSearchParams<{ id: string; resume?: string }>();
  const router = useRouter();
  const explicit = resume != null && resume !== "" ? parseInt(resume, 10) || 0 : null;
  const progress = useProgress(explicit == null ? id ?? "" : "");
  const waiting = explicit == null && !!id && progress.isLoading;
  const resumeSec = explicit ?? resumePointFor(progress.data);

  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <StatusBar hidden />
      <QueryState
        isLoading={waiting}
        isError={!id}
        data={id ? { id } : undefined}
        onRetry={() => router.back()}
      >
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
