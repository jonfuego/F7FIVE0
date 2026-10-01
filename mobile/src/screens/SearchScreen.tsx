import { useRouter } from "expo-router";
import React, { useEffect, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { useSearch } from "@/api/queries";
import { colors, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { QueryState } from "@/ui/QueryState";
import { RefreshableGrid } from "@/ui/RefreshableGrid";
import { Screen } from "@/ui/Screen";
import { TrackRow } from "@/ui/TrackRow";

export default function SearchScreen(): React.ReactElement {
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const router = useRouter();

  // Debounce input by 300ms (polish: search debounce).
  useEffect(() => {
    const t = setTimeout(() => setDebounced(text), 300);
    return () => clearTimeout(t);
  }, [text]);

  const results = useSearch(debounced);

  return (
    <Screen title="Search">
      <View style={styles.searchBox}>
        <TextInput
          style={styles.input}
          placeholder="Search movies, shows, music…"
          placeholderTextColor={colors.textFaint}
          value={text}
          onChangeText={setText}
          autoCorrect={false}
          returnKeyType="search"
          accessibilityLabel="Search query"
        />
      </View>
      {debounced.trim().length === 0 ? (
        <View style={styles.hint} />
      ) : (
        <QueryState
          isLoading={results.isLoading}
          isError={results.isError}
          data={results.data}
          onRetry={results.refetch}
          isEmpty={(d) => d.length === 0}
          emptyTitle="No results"
          emptyMessage={`Nothing matched "${debounced}".`}
        >
          {(rows) => (
            <RefreshableGrid
              data={rows}
              keyExtractor={(r) => `${r.kind}-${r.id}`}
              refreshing={results.isFetching}
              onRefresh={results.refetch}
              renderItem={({ item }) => (
                <TrackRow
                  title={item.title}
                  subtitle={item.subtitle ?? item.kind}
                  artPath={item.poster_path}
                  onPress={() => {
                    if (item.kind === "album") router.push(`/music/album/${item.id}`);
                    else if (item.kind === "movie") router.push(`/movies/movie/${item.id}`);
                    else if (item.kind === "series") router.push(`/movies/show/${item.id}`);
                    else router.push(`/watch/${item.id}?kind=${item.kind}`);
                  }}
                />
              )}
            />
          )}
        </QueryState>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  searchBox: { paddingVertical: spacing.sm },
  input: {
    minHeight: MIN_TOUCH,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
    color: colors.text,
    fontSize: 16,
  },
  hint: { flex: 1 },
});
