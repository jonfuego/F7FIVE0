import { QueryClientProvider } from "@tanstack/react-query";
import { Stack, useRouter, useSegments } from "expo-router";
import { StatusBar } from "expo-status-bar";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { createApiClient } from "@/api/client";
import { reportClientError } from "@/api/media";
import { secureTokenStore } from "@/api/tokenStore";
import type { MinVersions } from "@/api/types";
import { DownloadProvider } from "@/download/DownloadProvider";
import { AndroidAutoBridge } from "@/player/AndroidAutoBridge";
import { PlayerProvider } from "@/player/PlayerProvider";
import { AuthProvider, useApi, useAuth } from "@/state/auth";
import { APP_VERSION, clientPlatform, getApiBase, loadServerUrl } from "@/state/config";
import { useAppFonts } from "@/state/fonts";
import { queryClient } from "@/state/query";
import { colors } from "@/state/theme";
import { ErrorBoundary } from "@/ui/ErrorBoundary";
import { UpdateRequired } from "@/ui/UpdateRequired";
import { isUpdateRequiredForPlatform } from "@/lib/version";

function Loading(): React.ReactElement {
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background }}>
      <ActivityIndicator size="large" color={colors.accent} />
    </View>
  );
}

/** Launch-time min-version gate. Uses an unauthenticated client so it runs
 * before login. Fails open (never blocks) if the check can't be reached. */
function useMinVersionGate(serverReady: boolean): "checking" | "ok" | "update" {
  const [state, setState] = useState<"checking" | "ok" | "update">("checking");
  useEffect(() => {
    if (!serverReady) return;
    if (!getApiBase()) {
      // No server chosen yet (first launch): nothing to check against.
      setState("ok");
      return;
    }
    let active = true;
    const client = createApiClient({ baseUrl: getApiBase(), tokenStore: secureTokenStore });
    client
      .json<MinVersions>("/api/client/min-version")
      .then((mins) => {
        if (!active) return;
        const needs = isUpdateRequiredForPlatform(APP_VERSION, clientPlatform(), mins);
        setState(needs ? "update" : "ok");
      })
      .catch(() => active && setState("ok"));
    return () => {
      active = false;
    };
  }, [serverReady]);
  return state;
}

/** Load the saved server address before anything talks to the network. */
function useServerReady(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    loadServerUrl().finally(() => setReady(true));
  }, []);
  return ready;
}

function AuthGate(): React.ReactElement {
  const { status } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") return;
    const inAuth = segments[0] === "login";
    if (status === "signedOut" && !inAuth) {
      router.replace("/login");
    } else if (status === "signedIn" && inAuth) {
      router.replace("/");
    }
  }, [status, segments, router]);

  if (status === "loading") return <Loading />;

  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.background } }}>
      <Stack.Screen name="login" />
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="now-playing" options={{ presentation: "modal", animation: "slide_from_bottom" }} />
      <Stack.Screen name="watch/[id]" options={{ presentation: "fullScreenModal" }} />
    </Stack>
  );
}

/** Wraps the app in an error boundary that reports crashes to the backend
 * (Phase 4 crash reporting, no third-party service). */
function GatedApp(): React.ReactElement {
  const api = useApi();
  return (
    <ErrorBoundary
      onError={(error, info) =>
        void reportClientError(api, {
          message: error.message,
          stack: info.componentStack,
          platform: clientPlatform(),
          client_version: APP_VERSION,
          fatal: true,
          context: "error-boundary",
        })
      }
    >
      <AuthGate />
    </ErrorBoundary>
  );
}

export default function RootLayout(): React.ReactElement {
  const serverReady = useServerReady();
  const gate = useMinVersionGate(serverReady);
  const [fontsLoaded] = useAppFonts();

  if (!serverReady) {
    return (
      <GestureHandlerRootView style={{ flex: 1 }}>
        <Loading />
      </GestureHandlerRootView>
    );
  }

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <DownloadProvider>
            <PlayerProvider>
              <AndroidAutoBridge />
              <StatusBar style="light" />
              {!fontsLoaded || gate === "checking" ? (
                <Loading />
              ) : gate === "update" ? (
                <UpdateRequired />
              ) : (
                <GatedApp />
              )}
            </PlayerProvider>
            </DownloadProvider>
          </AuthProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
