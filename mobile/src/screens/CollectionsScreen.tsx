import { useRouter } from "expo-router";
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useApi } from "@/state/auth";
import { colors, fonts, spacing, typography } from "@/state/theme";

type CollectionSummary = {
  id: string;
  name: string;
  kind: string | null;
  item_count: number;
  tmdb_collection_id: number | null;
  is_auto: boolean;
  description: string | null;
};

export default function CollectionsScreen(): React.ReactElement {
  const api = useApi();
  const router = useRouter();
  const [collections, setCollections] = useState<CollectionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.json<CollectionSummary[]>("/api/library/collections");
        if (!cancelled) setCollections(data);
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load collections");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api]);

  if (error) {
    return (
      <SafeAreaView style={styles.container}>
        <Text style={styles.error}>{error}</Text>
      </SafeAreaView>
    );
  }

  if (collections === null) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator color={colors.hive} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <Text style={styles.title}>Collections</Text>
      {collections.length === 0 ? (
        <Text style={styles.empty}>No collections yet.</Text>
      ) : (
        <FlatList
          data={collections}
          keyExtractor={(c) => c.id}
          numColumns={2}
          contentContainerStyle={styles.grid}
          columnWrapperStyle={styles.row}
          renderItem={({ item }) => (
            <Pressable
              style={styles.card}
              onPress={() => router.push(`/movies/collection/${item.id}`)}
            >
              <View style={styles.poster}>
                <Text style={styles.posterInitial}>
                  {item.name.charAt(0).toUpperCase()}
                </Text>
              </View>
              <Text style={styles.name} numberOfLines={2}>
                {item.name}
              </Text>
              <Text style={styles.count}>
                {item.item_count} {item.item_count === 1 ? "movie" : "movies"}
              </Text>
            </Pressable>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  title: {
    ...typography.title,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
  },
  empty: {
    ...typography.body,
    color: colors.textMuted,
    paddingHorizontal: spacing.lg,
  },
  error: {
    ...typography.body,
    color: colors.hiveText,
    paddingHorizontal: spacing.lg,
  },
  grid: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xl,
  },
  row: {
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  card: {
    flex: 1,
  },
  poster: {
    aspectRatio: 2 / 3,
    backgroundColor: colors.surfaceAlt,
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xs,
  },
  posterInitial: {
    fontSize: 32,
    color: colors.textMuted,
    fontFamily: fonts.ui,
  },
  name: {
    ...typography.body,
    fontFamily: fonts.uiBold,
    fontSize: 13,
  },
  count: {
    ...typography.caption,
  },
});
