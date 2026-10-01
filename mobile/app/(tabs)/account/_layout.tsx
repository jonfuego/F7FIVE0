import { Stack } from "expo-router";
import React from "react";

import { colors } from "@/state/theme";

export default function AccountLayout(): React.ReactElement {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
