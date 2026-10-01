import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import {
  deletePasskey,
  listPasskeys,
  registerPasskey,
  renamePasskey,
  type PasskeyDTO,
} from "@/auth/passkey";
import { useApi } from "@/state/auth";
import { getApiBase } from "@/state/config";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { IconButton } from "@/ui/IconButton";
import { Screen } from "@/ui/Screen";

// Passkeys management (crit 19): add / list / rename / delete, all through
// src/auth/passkey.ts. Registration runs the Android Credential Manager create
// ceremony (fingerprint / device lock) and stores the new credential.
export default function PasskeysScreen(): React.ReactElement {
  const api = useApi();
  const [items, setItems] = useState<PasskeyDTO[] | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setError(false);
      setItems(await listPasskeys(api));
    } catch {
      setError(true);
      setItems([]);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onAdd = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      await registerPasskey(api);
      Alert.alert("Passkey added", "You can now sign in with your fingerprint.");
      await refresh();
    } catch (e) {
      Alert.alert(
        "Couldn't add passkey",
        e instanceof Error && e.message.includes("cancel")
          ? "Setup was cancelled."
          : "Passkey setup failed or was cancelled.",
      );
    } finally {
      setBusy(false);
    }
  }, [api, busy, refresh]);

  const onRename = useCallback(
    (p: PasskeyDTO) => {
      Alert.prompt?.(
        "Rename passkey",
        "Enter a new name",
        async (next?: string) => {
          const name = (next ?? "").trim();
          if (!name || name === p.name) return;
          try {
            await renamePasskey(api, p.id, name);
            await refresh();
          } catch {
            Alert.alert("Couldn't rename", "Please try again.");
          }
        },
        "plain-text",
        p.name,
      );
    },
    [api, refresh],
  );

  const onDelete = useCallback(
    (p: PasskeyDTO) => {
      Alert.alert("Remove passkey", `Remove "${p.name}"? You'll need another way to sign in.`, [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: async () => {
            try {
              await deletePasskey(api, p.id);
              await refresh();
            } catch {
              Alert.alert("Couldn't remove", "Please try again.");
            }
          },
        },
      ]);
    },
    [api, refresh],
  );

  return (
    <Screen title="Passkeys">
      <ScrollView>
        <Text style={styles.intro}>
          Sign in with your fingerprint or device lock instead of a password. Your
          passkey works in the app and in a browser at {getApiBase().replace(/^https?:\/\//, "")}.
        </Text>

        {items === null ? (
          <ActivityIndicator color={colors.accent} style={{ marginTop: spacing.lg }} />
        ) : error ? (
          <Text style={styles.error}>Couldn&apos;t load your passkeys.</Text>
        ) : items.length === 0 ? (
          <Text style={styles.empty}>No passkeys yet.</Text>
        ) : (
          items.map((p) => (
            <View key={p.id} style={styles.row}>
              <Ionicons name="finger-print" size={22} color={colors.accent} />
              <View style={styles.meta}>
                <Text style={styles.name}>{p.name}</Text>
                <Text style={styles.sub}>
                  Added {formatDate(p.created_at)}
                  {p.last_used_at ? ` · last used ${formatDate(p.last_used_at)}` : ""}
                </Text>
              </View>
              <IconButton
                name="create-outline"
                onPress={() => onRename(p)}
                accessibilityLabel={`Rename ${p.name}`}
                color={colors.textMuted}
              />
              <IconButton
                name="trash-outline"
                onPress={() => onDelete(p)}
                accessibilityLabel={`Delete ${p.name}`}
                color={colors.danger}
              />
            </View>
          ))
        )}

        <Pressable
          onPress={() => void onAdd()}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel="Add a passkey"
          style={({ pressed }) => [styles.addBtn, (pressed || busy) && styles.addBtnDim]}
        >
          <Text style={styles.addText}>{busy ? "Setting up..." : "Add a passkey"}</Text>
        </Pressable>
      </ScrollView>
    </Screen>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

const styles = StyleSheet.create({
  intro: { ...typography.body, color: colors.textMuted, marginBottom: spacing.md },
  error: { ...typography.body, color: colors.danger, marginTop: spacing.lg },
  empty: { ...typography.body, color: colors.textFaint, marginTop: spacing.lg },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: MIN_TOUCH + 8,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  meta: { flex: 1 },
  name: { ...typography.body, fontWeight: "600" },
  sub: { ...typography.caption },
  addBtn: {
    minHeight: MIN_TOUCH,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    backgroundColor: colors.bulb,
    marginTop: spacing.xl,
  },
  addBtnDim: { opacity: 0.6 },
  addText: { fontFamily: fonts.uiSemiBold, color: colors.background, fontSize: 15 },
});
