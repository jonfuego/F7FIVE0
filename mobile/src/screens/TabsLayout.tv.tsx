import { BottomTabBar } from "@react-navigation/bottom-tabs";
import { Tabs } from "expo-router";
import { Film, Home, Music, Search } from "lucide-react-native";
import React from "react";
import { View } from "react-native";

import { colors } from "@/state/theme";
import { Icon } from "@/ui/Icon";
import { MiniPlayer } from "@/ui/MiniPlayer";

/** Android TV navigation (spec F): Home (10-foot browse rails), Music, Movies &
 * Shows and Search, all D-pad focusable. The Account tab (requests, sessions,
 * downloads) is hidden on TV: no requests or admin surfaces on the big screen. */
export default function TvTabsLayout(): React.ReactElement {
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
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { fontSize: 24 },
        tabBarStyle: {
          height: 72,
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
        },
      }}
      sceneContainerStyle={{ backgroundColor: colors.background }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          tabBarIcon: ({ color }) => <Icon icon={Home} color={color} size={26} />,
        }}
      />
      <Tabs.Screen
        name="music"
        options={{
          title: "Music",
          tabBarIcon: ({ color }) => <Icon icon={Music} color={color} size={26} />,
        }}
      />
      <Tabs.Screen
        name="movies"
        options={{
          title: "Movies & Shows",
          tabBarIcon: ({ color }) => <Icon icon={Film} color={color} size={26} />,
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          title: "Search",
          tabBarIcon: ({ color }) => <Icon icon={Search} color={color} size={26} />,
        }}
      />
      {/* Not reachable on TV. */}
      <Tabs.Screen name="account" options={{ href: null }} />
    </Tabs>
  );
}
