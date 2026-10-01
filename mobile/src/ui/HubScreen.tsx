import React from "react";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSetting } from "@/state/settings";
import { colors } from "@/state/theme";
import { ChipBar, type ChipOption } from "./ChipBar";
import { PageTitle } from "./PageTitle";

export interface HubSection extends ChipOption {
  /** Big page title shown while this chip is selected. */
  title: string;
  render: (select: (key: string) => void) => React.ReactNode;
}

interface HubScreenProps {
  /** Settings key the selected chip is remembered under. */
  storageKey: string;
  sections: HubSection[];
  /** The marquee header (the route passes <MarqueeHeader />). */
  header: React.ReactNode;
}

/** Tab root for Music and Movies & Shows, laid out like the PWA's library
 * pages: F7FIVE0 marquee, a big Bebas title, a BROWSE chip row, then either the
 * "All" rails or the chosen grid inline (no plain list of links). The chosen
 * chip is remembered per hub. */
export function HubScreen({ storageKey, sections, header }: HubScreenProps): React.ReactElement {
  const [selected, setSelected] = useSetting<string>(storageKey, sections[0].key);
  const current = sections.find((s) => s.key === selected) ?? sections[0];
  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      {header}
      <PageTitle>{current.title}</PageTitle>
      <ChipBar
        label="Browse"
        options={sections.map(({ key, label }) => ({ key, label }))}
        value={current.key}
        onChange={setSelected}
      />
      <View style={styles.body}>{current.render(setSelected)}</View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  body: { flex: 1 },
});
