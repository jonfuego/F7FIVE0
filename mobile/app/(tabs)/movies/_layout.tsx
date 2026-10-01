import { Stack } from "expo-router";
import React from "react";

import { colors } from "@/state/theme";

export default function MoviesLayout(): React.ReactElement {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
