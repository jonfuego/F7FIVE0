import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, spacing, typography } from "@/state/theme";
import { Screen } from "@/ui/Screen";

/** TV build: media requests are a phone/web feature (spec F: no requests or
 * admin on TV). The route still exists because both builds share app/, so the
 * TV bundle renders this notice instead of the request UI. */
export default function TvRequestsUnavailable(): React.ReactElement {
  return (
    <Screen title="Requests">
      <View style={styles.box}>
        <Text style={typography.heading}>Not on TV</Text>
        <Text style={styles.body}>Request new titles from the F7FIVE0 app on your phone or the web.</Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  box: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  body: { ...typography.body, color: colors.textMuted, textAlign: "center" },
});
