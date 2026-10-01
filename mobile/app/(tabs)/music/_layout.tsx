import { Stack } from "expo-router";
import React from "react";

import { colors } from "@/state/theme";

export default function MusicLayout(): React.ReactElement {
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
        contentStyle: { backgroundColor: colors.background },
        headerShown: false,
      }}
    />
  );
}
