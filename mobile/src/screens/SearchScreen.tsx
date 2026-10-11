import { useRouter } from "expo-router";
import React, { useEffect, useMemo, useState } from "react";
import { RefreshControl, SectionList, StyleSheet, Text, TextInput, View } from "react-native";

import { useSearch } from "@/api/queries";
import type { SearchResult } from "@/api/types";
import { groupSearchResults } from "@/lib/searchGroups";
import { colors, fonts, MIN_TOUCH, radius, spacing } from "@/state/theme";
import { QueryState } from "@/ui/QueryState";
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

  const results = useSearch(debounced, { artists: true });
  const sections = useMemo(() => groupSearchResults(results.data), [results.data]);

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
          {() => (
            <SectionList
              sections={sections}
              keyExtractor={(r: SearchResult) => `${r.kind}-${r.id}`}
              stickySectionHeadersEnabled={false}
              showsVerticalScrollIndicator={false}
              contentContainerStyle={styles.content}
              refreshControl={
                <RefreshControl
                  refreshing={results.isFetching}
                  onRefresh={results.refetch}
                  tintColor={colors.accent}
                  colors={[colors.accent]}
                />
              }
              renderSectionHeader={({ section }) => (
                <Text style={styles.sectionHeader} accessibilityRole="header">
                  {section.title}
                </Text>
              )}
              renderItem={({ item }) => (
                <TrackRow
                  title={item.title}
                  subtitle={item.subtitle ?? (item.kind === "artist" ? "Artist" : item.kind)}
                  artPath={item.poster_path}
                  onPress={() => {
                    if (item.kind === "artist") router.push(`/music/artist/${item.id}`);
                    else if (item.kind === "album") router.push(`/music/album/${item.id}`);
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
  content: { paddingBottom: 120, paddingTop: spacing.sm },
  sectionHeader: {
    fontFamily: fonts.display,
    fontSize: 20,
    letterSpacing: 1,
    color: colors.text,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
    backgroundColor: colors.background,
  },
});
