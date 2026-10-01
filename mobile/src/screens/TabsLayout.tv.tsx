import { Ionicons } from "@expo/vector-icons";
import { BottomTabBar } from "@react-navigation/bottom-tabs";
import { Tabs } from "expo-router";
import React from "react";
import { View } from "react-native";

import { colors } from "@/state/theme";
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
        tabBarActiveTintColor: colors.bulb,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { fontSize: 16 },
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
          tabBarIcon: ({ color }) => <Ionicons name="home" color={color} size={26} />,
        }}
      />
      <Tabs.Screen
        name="music"
        options={{
          title: "Music",
          tabBarIcon: ({ color }) => <Ionicons name="musical-notes" color={color} size={26} />,
        }}
      />
      <Tabs.Screen
        name="movies"
        options={{
          title: "Movies & Shows",
          tabBarIcon: ({ color }) => <Ionicons name="film" color={color} size={26} />,
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          title: "Search",
          tabBarIcon: ({ color }) => <Ionicons name="search" color={color} size={26} />,
        }}
      />
      {/* Not reachable on TV. */}
      <Tabs.Screen name="account" options={{ href: null }} />
    </Tabs>
  );
}
