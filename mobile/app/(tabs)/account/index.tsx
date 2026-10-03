import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import {
  ChevronRight,
  Download,
  Fingerprint,
  PlusCircle,
  Smartphone,
  Tv,
  XCircle,
} from "lucide-react-native";
import React, { useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View, RefreshControl } from "react-native";

import { changePassword, updateProfile } from "@/api/media";
import { revokeOtherSessions, revokeSession, useMySessions } from "@/api/queries";
import type { DeviceSession } from "@/api/types";
import { AuthError } from "@/api/client";
import { useApi, useAuth } from "@/state/auth";
import { passkeysAvailable } from "@/auth/passkey";
import { getApiBase } from "@/state/config";
import { colors, fonts, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Icon } from "@/ui/Icon";
import { IconButton } from "@/ui/IconButton";
import { QueryState } from "@/ui/QueryState";
import { Screen } from "@/ui/Screen";

export default function AccountScreen(): React.ReactElement {
  const sessions = useMySessions();
  const api = useApi();
  const { signOut } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  // Requests only exist on servers connected to Radarr / Sonarr.
  const features = useQuery({
    queryKey: ["client-features"],
    queryFn: () =>
      api.json<{ requests: { enabled: boolean }; passkeys?: { enabled: boolean } }>("/api/client/features"),
    staleTime: 5 * 60_000,
  });
  const requestsOn = features.data?.requests.enabled ?? false;
  // Passkeys need an https server and a phone (not TV) with a screen lock.
  const passkeysOn = (features.data?.passkeys?.enabled ?? false) && passkeysAvailable();

  // Edit display name (PATCH /api/auth/me).
  const [name, setName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const saveName = async () => {
    if (!name.trim()) return;
    setSavingName(true);
    try {
      await updateProfile(api, name.trim());
      Alert.alert("Saved", "Your display name was updated.");
      setName("");
    } catch (e) {
      Alert.alert("Couldn't save", e instanceof Error ? e.message : "Please try again.");
    } finally {
      setSavingName(false);
    }
  };

  // Change password (POST /api/auth/me/password).
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [savingPw, setSavingPw] = useState(false);
  const savePassword = async () => {
    if (!curPw || newPw.length < 8) {
      Alert.alert("Check the fields", "Enter your current password and a new one of at least 8 characters.");
      return;
    }
    setSavingPw(true);
    try {
      await changePassword(api, curPw, newPw);
      Alert.alert("Password changed", "Use your new password next time you sign in.");
      setCurPw("");
      setNewPw("");
    } catch (e) {
      const msg = e instanceof AuthError ? "Your current password is incorrect." : e instanceof Error ? e.message : "Please try again.";
      Alert.alert("Couldn't change password", msg);
    } finally {
      setSavingPw(false);
    }
  };

  const revokeOne = async (s: DeviceSession) => {
    if (s.current) return;
    setBusy(true);
    try {
      await revokeSession(api, s.id);
      await sessions.refetch();
    } finally {
      setBusy(false);
    }
  };

  const revokeOthers = () => {
    Alert.alert("Sign out other devices", "This signs out every device except this one.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Sign out others",
        style: "destructive",
        onPress: async () => {
          setBusy(true);
          try {
            await revokeOtherSessions(api);
            await sessions.refetch();
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  return (
    <Screen title="Account">
      <ScrollView
        refreshControl={
          <RefreshControl refreshing={sessions.isFetching} onRefresh={sessions.refetch} tintColor={colors.accent} />
        }
      >
        {requestsOn ? (
          <Pressable
            onPress={() => router.push("/account/requests")}
            accessibilityRole="button"
            accessibilityLabel="My requests"
            style={styles.link}
          >
            <Icon icon={PlusCircle} size={22} color={colors.accent} />
            <Text style={styles.linkText}>My requests</Text>
            <Icon icon={ChevronRight} size={20} color={colors.textFaint} />
          </Pressable>
        ) : null}

        <Pressable
          onPress={() => router.push("/account/downloads")}
          accessibilityRole="button"
          accessibilityLabel="Downloads"
          style={styles.link}
        >
          <Icon icon={Download} size={22} color={colors.accent} />
          <Text style={styles.linkText}>Downloads</Text>
          <Icon icon={ChevronRight} size={20} color={colors.textFaint} />
        </Pressable>

        {passkeysOn ? (
          <Pressable
            onPress={() => router.push("/account/passkeys")}
            accessibilityRole="button"
            accessibilityLabel="Passkeys"
            style={styles.link}
          >
            <Icon icon={Fingerprint} size={22} color={colors.accent} />
            <Text style={styles.linkText}>Passkeys</Text>
            <Icon icon={ChevronRight} size={20} color={colors.textFaint} />
          </Pressable>
        ) : null}

        <Text
          style={{ color: colors.textFaint, paddingHorizontal: spacing.lg, marginTop: spacing.sm }}
          accessibilityLabel="Server address"
        >
          Server: {getApiBase()} (sign out to switch servers)
        </Text>

        <Text style={styles.section}>Profile</Text>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="New display name"
          placeholderTextColor={colors.textFaint}
          autoCapitalize="words"
          accessibilityLabel="Display name"
        />
        <Pressable
          onPress={() => void saveName()}
          disabled={savingName || !name.trim()}
          accessibilityRole="button"
          accessibilityLabel="Save display name"
          style={({ pressed }) => [styles.saveBtn, (pressed || savingName || !name.trim()) && styles.saveBtnDim]}
        >
          <Text style={styles.saveText}>{savingName ? "Saving..." : "Save name"}</Text>
        </Pressable>

        <Text style={styles.section}>Change password</Text>
        <TextInput
          style={styles.input}
          value={curPw}
          onChangeText={setCurPw}
          placeholder="Current password"
          placeholderTextColor={colors.textFaint}
          secureTextEntry
          accessibilityLabel="Current password"
        />
        <TextInput
          style={styles.input}
          value={newPw}
          onChangeText={setNewPw}
          placeholder="New password (min 8 chars)"
          placeholderTextColor={colors.textFaint}
          secureTextEntry
          accessibilityLabel="New password"
        />
        <Pressable
          onPress={() => void savePassword()}
          disabled={savingPw}
          accessibilityRole="button"
          accessibilityLabel="Change password"
          style={({ pressed }) => [styles.saveBtn, (pressed || savingPw) && styles.saveBtnDim]}
        >
          <Text style={styles.saveText}>{savingPw ? "Saving..." : "Change password"}</Text>
        </Pressable>

        <Text style={styles.section}>Devices</Text>
        <QueryState
          isLoading={sessions.isLoading}
          isError={sessions.isError}
          data={sessions.data}
          onRetry={sessions.refetch}
          isEmpty={(d) => d.length === 0}
          emptyTitle="No active sessions"
          emptyMessage="Signed-in devices will appear here."
        >
          {(rows) => (
            <View>
              {rows.map((s) => (
                <View key={s.id} style={styles.sessionRow}>
                  <Icon
                    icon={s.platform === "android_tv" || s.platform === "tvos" ? Tv : Smartphone}
                    size={22}
                    color={colors.textMuted}
                  />
                  <View style={styles.sessionMeta}>
                    <Text style={styles.sessionName}>
                      {s.device_label ?? "Device"} {s.current ? "· This device" : ""}
                    </Text>
                    <Text style={styles.sessionSub}>
                      {[s.platform, s.client_version].filter(Boolean).join(" · ")}
                    </Text>
                  </View>
                  {s.current ? (
                    <Text style={styles.current}>current</Text>
                  ) : (
                    <IconButton
                      icon={XCircle}
                      onPress={() => revokeOne(s)}
                      accessibilityLabel={`Revoke ${s.device_label ?? "device"}`}
                      color={colors.danger}
                      disabled={busy}
                    />
                  )}
                </View>
              ))}
              {rows.length > 1 ? (
                <Pressable
                  onPress={revokeOthers}
                  accessibilityRole="button"
                  accessibilityLabel="Sign out all other devices"
                  style={styles.dangerBtn}
                >
                  <Text style={styles.dangerText}>Sign out all other devices</Text>
                </Pressable>
              ) : null}
            </View>
          )}
        </QueryState>

        <Pressable
          onPress={signOut}
          accessibilityRole="button"
          accessibilityLabel="Sign out"
          style={styles.signOut}
        >
          <Text style={styles.signOutText}>Sign out</Text>
        </Pressable>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  link: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    minHeight: MIN_TOUCH + 8,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    marginVertical: spacing.sm,
  },
  linkText: { ...typography.body, flex: 1, fontWeight: "600" },
  section: { ...typography.label, marginTop: spacing.lg, marginBottom: spacing.sm },
  input: {
    minHeight: MIN_TOUCH,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    color: colors.text,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
    fontFamily: fonts.ui,
    fontSize: 15,
  },
  saveBtn: {
    minHeight: MIN_TOUCH,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
  },
  saveBtnDim: { opacity: 0.6 },
  saveText: { fontFamily: fonts.uiSemiBold, color: colors.background, fontSize: 15 },
  sessionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    minHeight: MIN_TOUCH + 8,
    paddingHorizontal: spacing.sm,
  },
  sessionMeta: { flex: 1 },
  sessionName: { ...typography.body },
  sessionSub: { ...typography.caption },
  current: { ...typography.caption, color: colors.accent },
  dangerBtn: {
    minHeight: MIN_TOUCH,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.md,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.danger,
  },
  dangerText: { color: colors.danger, fontWeight: "600" },
  signOut: {
    minHeight: MIN_TOUCH + 4,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.xl,
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
  },
  signOutText: { ...typography.body, color: colors.text, fontWeight: "700" },
});
