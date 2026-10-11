// Pure rules for whether a collapsible Admin section is open (batch 7 item 8).
// Kept apart from the React component so node:test covers it (collapsible.test.ts).
//
// Inputs:
//   collapsed   the saved fold state for the section (admin.collapsed).
//   forceOpen   the section needs attention (a running or failed scan, an
//               update available or running, a #metadata link).
//   userChoice  what the user last did with the chevron on this page view:
//               "open", "closed", or null for no click yet.
//
// The rule: a click always wins over forceOpen, until forceOpen newly appears.
//   - no click: open when not collapsed, or when forceOpen (attention keeps a
//     fold from hiding something that matters, including on page load).
//   - clicked: open or closed exactly as the user chose, even with forceOpen set.
//   - forceOpen going from false to true (attention newly appears) clears the
//     click, so a new problem opens a section the user had folded. Attention
//     that stays set, or clears, leaves the click alone.
// The saved fold state still follows every click (see storedNeedsToggle), so a
// reload remembers it; on reload attention forces the section open again.

export type UserChoice = "open" | "closed" | null;

export function isSectionOpen(collapsed: boolean, forceOpen: boolean, userChoice: UserChoice): boolean {
  if (userChoice !== null) return userChoice === "open";
  return !collapsed || forceOpen;
}

// The choice a click on the chevron records, given what is shown right now.
export function choiceAfterClick(openNow: boolean): UserChoice {
  return openNow ? "closed" : "open";
}

// Keep or clear the click when forceOpen changes. Only the false -> true edge
// clears it.
export function choiceAfterForceChange(prevForce: boolean, nextForce: boolean, userChoice: UserChoice): UserChoice {
  return !prevForce && nextForce ? null : userChoice;
}

// A click should flip the saved fold state only when it does not already match
// what the user chose. Example: saved collapsed, attention forces it open, the
// user clicks to close: the saved state is already collapsed, so do not flip it
// to "open".
export function storedNeedsToggle(collapsed: boolean, openAfterClick: boolean): boolean {
  return collapsed === openAfterClick;
}
