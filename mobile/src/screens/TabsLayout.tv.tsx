import { BottomTabBar } from "@react-navigation/bottom-tabs";
import { Tabs } from "expo-router";
import { Film, Home, Music, Search } from "lucide-react-native";
import React from "react";
import { View } from "react-native";

import { colors } from "@/state/theme";
import { Icon } from "@/ui/Icon";
import { MiniPlayer } from "@/ui/MiniPlayer";
import { isTabVisible } from "./tabs";

/** Android TV navigation (spec F): Home (10-foot browse rails), Music, Movies &
 * Shows and Search, all D-pad focusable. Only the tabs in TV_TABS (./tabs) show:
 * every other route is hidden, so the Account tab (requests, sessions, downloads)
 * and any tab added for the phone stay off the big screen. */
export default function TvTabsLayout(): React.ReactElement {
  return (
    <Tabs
      tabBar={(props) => (
        <View>
          <MiniPlayer />
          <BottomTabBar {...props} />
        </View>
      )}
      screenOptions={({ route }) => ({
        headerShown: false,
        sceneStyle: { backgroundColor: colors.background },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarLabelStyle: { fontSize: 24 },
        tabBarStyle: {
          height: 72,
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
        },
        // Not in TV_TABS: no button, so nothing on the big screen links to it.
        ...(isTabVisible(route.name, true) ? {} : { tabBarButton: () => null }),
      })}
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
    </Tabs>
  );
}
