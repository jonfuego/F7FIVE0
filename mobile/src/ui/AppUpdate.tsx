/** "Update from your server". The server ships the phone app that matches
 * its own version (setup copies it in), so when the server is upgraded this
 * offers the new build. The download is a signed link opened in the browser;
 * Android installs it over this app because the signing key is the same.
 *
 * Android phones only. TV builds are a separate download. */
import { useQuery } from "@tanstack/react-query";
import { CloudDownload } from "lucide-react-native";
import React, { useEffect } from "react";
import { Alert, Linking, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import * as SecureStore from "expo-secure-store";

import { formatSize, newerServerVersion, type ServerAppInfo } from "@/lib/appUpdate";
import { useApi, useAuth } from "@/state/auth";
import { APP_VERSION, IS_TV } from "@/state/config";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { Icon } from "@/ui/Icon";

const PROMPTED_KEY = "f7five0.update_prompted";
const SUPPORTED = Platform.OS === "android" && !IS_TV;

export function useServerAppUpdate(): { info: ServerAppInfo | undefined; newer: string | null } {
  const api = useApi();
  const { status } = useAuth();
  const q = useQuery({
    queryKey: ["server-android-app"],
    queryFn: () => api.json<ServerAppInfo>("/api/client/android-app"),
    enabled: SUPPORTED && status === "signedIn",
    // The signed link lasts an hour; refetch well before that.
    staleTime: 20 * 60_000,
    retry: false,
  });
  return { info: q.data, newer: newerServerVersion(APP_VERSION, q.data) };
}

function openDownload(info: ServerAppInfo | undefined): void {
  if (!info?.url) return;
  void Linking.openURL(info.url).catch(() =>
    Alert.alert("Couldn't open the download", "Open your F7FIVE0 server in a browser and use Account > Download for Android."),
  );
}

/** Account screen row. Renders nothing when the server has no app. */
export function AppUpdateCard(): React.ReactElement | null {
  const { info, newer } = useServerAppUpdate();
  if (!SUPPORTED || !info?.available) return null;
  if (!newer) {
    return (
      <Text style={styles.current}>
        App {APP_VERSION}. Your server offers {info.version}.
      </Text>
    );
  }
  return (
    <View style={styles.card}>
      <Icon icon={CloudDownload} size={22} color={colors.accent} />
      <View style={styles.cardText}>
        <Text style={styles.title}>Update to {newer}</Text>
        <Text style={styles.body}>
          From your server{info.size_bytes ? `, ${formatSize(info.size_bytes)}` : ""}. Open the download and tap
          Update.
        </Text>
      </View>
      <Pressable
        onPress={() => openDownload(info)}
        accessibilityRole="button"
        accessibilityLabel={`Update to ${newer}`}
        style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
      >
        <Text style={styles.buttonText}>Update</Text>
      </Pressable>
    </View>
  );
}

/** Asks once per new version, after sign-in. */
export function AppUpdatePrompt(): null {
  const { info, newer } = useServerAppUpdate();
  useEffect(() => {
    if (!newer) return;
    let alive = true;
    (async () => {
      let asked: string | null = null;
      try {
        asked = await SecureStore.getItemAsync(PROMPTED_KEY);
      } catch {
        // Ask anyway.
      }
      if (!alive || asked === newer) return;
      try {
        await SecureStore.setItemAsync(PROMPTED_KEY, newer);
      } catch {
        // Fine: worst case it asks again next launch.
      }
      Alert.alert(
        "Update available",
        `Your server has F7FIVE0 ${newer} (you have ${APP_VERSION}). It's also under Account.`,
        [
          { text: "Later", style: "cancel" },
          { text: "Update", onPress: () => openDownload(info) },
        ],
      );
    })();
    return () => {
      alive = false;
    };
  }, [newer, info]);
  return null;
}

/** The "Update required" screen's button. Before sign-in there is no token
 * for a signed link, so this opens the server's web download, which signs
 * in first when needed. */
export function openServerDownloadPage(base: string): void {
  if (!base) return;
  void Linking.openURL(`${base}/download/android`).catch(() => undefined);
}

export const appUpdateSupported = SUPPORTED;

const styles = StyleSheet.create({
  current: { ...typography.caption, color: colors.textFaint, paddingHorizontal: spacing.lg, marginTop: spacing.xs },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  cardText: { flex: 1, gap: 2 },
  title: { ...typography.body, color: colors.text, fontWeight: "700" },
  body: { ...typography.caption, color: colors.textMuted },
  button: {
    minHeight: MIN_TOUCH,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonPressed: { backgroundColor: colors.accentPressed },
  buttonText: { color: colors.onHive, fontWeight: "700" },
});
