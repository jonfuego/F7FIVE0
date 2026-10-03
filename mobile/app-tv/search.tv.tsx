import { useRouter } from "expo-router";
import React, { useEffect, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { useSearch } from "@/api/queries";
import { colors, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";
import { Tile } from "@/ui/Tile";

/** TV search: remote-driven text entry + focusable result grid. */
export default function TvSearch(): React.ReactElement {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const router = useRouter();

  useEffect(() => {
    const t = setTimeout(() => setQ(text), 300);
    return () => clearTimeout(t);
  }, [text]);

  const results = useSearch(q);

  return (
    <Screen title="Search">
      <View style={styles.box}>
        <TextInput
          style={styles.input}
          placeholder="Search"
          placeholderTextColor={colors.textFaint}
          value={text}
          onChangeText={setText}
          accessibilityLabel="Search query"
        />
      </View>
      {q.trim().length === 0 ? (
        <View style={styles.flex} />
      ) : (
        <QueryState isLoading={results.isLoading} isError={results.isError} data={results.data} onRetry={results.refetch} isEmpty={(d) => d.length === 0}>
          {(rows) => (
            <View style={styles.grid}>
              {rows.map((r) => (
                <Tile
                  key={`${r.kind}-${r.id}`}
                  title={r.title}
                  subtitle={r.subtitle ?? r.kind}
                  artPath={r.poster_path}
                  size={180}
                  onPress={() => {
                    if (r.kind === "album") router.push(`/music/album/${r.id}`);
                    else if (r.kind === "movie") router.push(`/movies/movie/${r.id}`);
                    else if (r.kind === "series") router.push(`/movies/show/${r.id}`);
                    else router.push(`/watch/${r.id}`);
                  }}
                />
              ))}
            </View>
          )}
        </QueryState>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  box: { paddingVertical: spacing.md },
  input: {
    minHeight: MIN_TOUCH + 12,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    color: colors.text,
    fontSize: 24,
  },
  flex: { flex: 1 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.lg },
});
