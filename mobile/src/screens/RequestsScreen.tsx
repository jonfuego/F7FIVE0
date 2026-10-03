import React, { useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { createRequest, searchRequests } from "@/api/media";
import { useMyRequests } from "@/api/queries";
import type { RequestSearchResult } from "@/api/types";
import { useApi } from "@/state/auth";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";

const STATUS_COLOR: Record<string, string> = {
  pending: colors.accent,
  approved: "#22c55e",
  available: "#22c55e",
  denied: colors.danger,
};

export default function RequestsScreen(): React.ReactElement {
  const api = useApi();
  const requests = useMyRequests();
  const [kind, setKind] = useState<"movie" | "series">("movie");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<RequestSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [requested, setRequested] = useState<Set<string>>(new Set());

  const runSearch = async () => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      setResults(await searchRequests(api, kind, q.trim()));
    } catch (e) {
      Alert.alert("Search failed", e instanceof Error ? e.message : "Please try again.");
    } finally {
      setSearching(false);
    }
  };

  const request = async (r: RequestSearchResult) => {
    try {
      await createRequest(api, r.kind || kind, r.external_id);
      setRequested((prev) => new Set(prev).add(r.external_id));
      void requests.refetch();
    } catch (e) {
      Alert.alert("Request failed", e instanceof Error ? e.message : "Please try again.");
    }
  };

  return (
    <Screen title="Requests">
      <ScrollView keyboardShouldPersistTaps="handled">
        <View style={styles.kindRow}>
          {(["movie", "series"] as const).map((k) => (
            <Pressable
              key={k}
              accessibilityRole="button"
              accessibilityState={{ selected: k === kind }}
              onPress={() => setKind(k)}
              style={[styles.chip, k === kind && styles.chipActive]}
            >
              <Text style={[styles.chipText, k === kind && styles.chipTextActive]}>
                {k === "movie" ? "Movie" : "TV"}
              </Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.searchRow}>
          <TextInput
            style={styles.input}
            value={q}
            onChangeText={setQ}
            placeholder={`Search for a ${kind === "movie" ? "movie" : "show"} to request`}
            placeholderTextColor={colors.textFaint}
            returnKeyType="search"
            onSubmitEditing={() => void runSearch()}
            accessibilityLabel="Request search"
          />
          <Pressable onPress={() => void runSearch()} accessibilityLabel="Search" style={styles.searchBtn}>
            <Text style={styles.searchBtnText}>Find</Text>
          </Pressable>
        </View>

        {searching ? <ActivityIndicator color={colors.accent} style={{ marginVertical: spacing.md }} /> : null}
        {results.map((r) => {
          const done = requested.has(r.external_id);
          return (
            <View key={`${r.kind}-${r.external_id}`} style={styles.resultRow}>
              <View style={styles.meta}>
                <Text style={styles.title} numberOfLines={1}>
                  {r.title} {r.year ? `(${r.year})` : ""}
                </Text>
                <Text style={styles.kindLabel}>{r.kind || kind}</Text>
              </View>
              <Pressable
                disabled={done}
                onPress={() => void request(r)}
                accessibilityRole="button"
                accessibilityLabel={done ? "Requested" : `Request ${r.title}`}
                style={[styles.reqBtn, done && styles.reqBtnDone]}
              >
                <Text style={[styles.reqText, done && styles.reqTextDone]}>{done ? "Requested" : "Request"}</Text>
              </Pressable>
            </View>
          );
        })}

        <Text style={styles.section}>My Requests</Text>
        <QueryState
          isLoading={requests.isLoading}
          isError={requests.isError}
          data={requests.data}
          onRetry={requests.refetch}
          isEmpty={(d) => d.length === 0}
          emptyTitle="No requests"
          emptyMessage="Titles you request show up here with their status."
        >
          {(rows) => (
            <View>
              {rows.map((item) => (
                <View key={item.id} style={styles.row}>
                  <View style={styles.meta}>
                    <Text style={styles.title} numberOfLines={1}>
                      {item.title} {item.year ? `(${item.year})` : ""}
                    </Text>
                    <Text style={styles.kindLabel}>{item.kind}</Text>
                  </View>
                  <Text style={[styles.status, { color: STATUS_COLOR[item.status] ?? colors.textMuted }]}>
                    {item.status}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </QueryState>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  kindRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  chip: {
    minHeight: 40,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
    justifyContent: "center",
  },
  chipActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { fontFamily: fonts.uiMedium, fontSize: 14, color: colors.text },
  chipTextActive: { color: colors.background, fontFamily: fonts.uiSemiBold },
  searchRow: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  input: {
    flex: 1,
    minHeight: MIN_TOUCH,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    color: colors.text,
    paddingHorizontal: spacing.md,
    fontFamily: fonts.ui,
    fontSize: 15,
  },
  searchBtn: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  searchBtnText: { fontFamily: fonts.uiSemiBold, color: colors.background, fontSize: 15 },
  resultRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  reqBtn: {
    minHeight: 40,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.accent,
    justifyContent: "center",
  },
  reqBtnDone: { borderColor: colors.textFaint },
  reqText: { fontFamily: fonts.uiSemiBold, color: colors.accent, fontSize: 14 },
  reqTextDone: { color: colors.textFaint },
  section: { ...typography.label, marginTop: spacing.xl, marginBottom: spacing.sm },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.md,
  },
  meta: { flex: 1 },
  title: { ...typography.body },
  kindLabel: { ...typography.caption, textTransform: "capitalize" },
  status: { ...typography.label, textTransform: "capitalize" },
});
