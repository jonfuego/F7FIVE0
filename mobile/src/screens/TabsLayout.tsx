import { BottomTabBar } from "@react-navigation/bottom-tabs";
import { Tabs, useRootNavigationState, useRouter } from "expo-router";
import { Film, Home, Music, Search, UserCircle } from "lucide-react-native";
import React, { useEffect, useRef } from "react";
import { View } from "react-native";

import { useDownloads } from "@/download/DownloadProvider";
import { colors } from "@/state/theme";
import { Icon } from "@/ui/Icon";
import { MiniPlayer } from "@/ui/MiniPlayer";

/** If the app starts with no network, open Downloads (spec J offline mode:
 * the app opens to what can play). Only at launch, never mid-session. */
const OFFLINE_LAUNCH_WINDOW_MS = 15_000;

/** Bottom tabs for phone: Home, Music, Movies & Shows, Search, Account. The
 * persistent MiniPlayer is rendered directly above the tab bar on every tab. */
export default function TabsLayout(): React.ReactElement {
  const router = useRouter();
  const { online } = useDownloads();
  const mountedAt = useRef(Date.now());
  const redirected = useRef(false);
  // Navigating before the root navigator has mounted throws ("Attempted to
  // navigate before mounting the Root Layout"), which is exactly what an
  // offline cold start hit. Wait for the root navigation state, then defer
  // the push one tick.
  const navReady = !!useRootNavigationState()?.key;
  useEffect(() => {
    if (!navReady || online || redirected.current) return;
    if (Date.now() - mountedAt.current > OFFLINE_LAUNCH_WINDOW_MS) return;
    redirected.current = true;
    const t = setTimeout(() => router.push("/account/downloads"), 0);
    return () => clearTimeout(t);
  }, [navReady, online, router]);

  return (
    <Tabs
      tabBar={(props) => (
        <View>
          <MiniPlayer />
          <BottomTabBar {...props} />
        </View>
      )}
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: colors.background },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          tabBarIcon: ({ color, size }) => <Icon icon={Home} color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="music"
        options={{
          title: "Music",
          tabBarIcon: ({ color, size }) => <Icon icon={Music} color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="movies"
        options={{
          title: "Movies & Shows",
          tabBarIcon: ({ color, size }) => <Icon icon={Film} color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          title: "Search",
          tabBarIcon: ({ color, size }) => <Icon icon={Search} color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="account"
        options={{
          title: "Account",
          tabBarIcon: ({ color, size }) => <Icon icon={UserCircle} color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
