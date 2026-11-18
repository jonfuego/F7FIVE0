/** Where a system link should take the app (expo-router `+native-intent`).
 *
 * Tapping the media notification opens the app with
 * `trackplayer://notification.click` (react-native-track-player puts that on
 * the notification's intent so apps can tell it apart). It is not a route, so
 * expo-router used to push its Not found screen on top of whatever the person
 * was on, and Back took them to the right place. Pure, so it is unit tested.
 *
 * - The app was already running: return "" so the router does nothing and the
 *   person stays where they were (the subscribe path skips a falsy href).
 * - The app was started by the tap: open Home, the same as the launcher.
 * - Anything else passes through unchanged. */
export function redirectSystemPath(path: string, initial: boolean): string {
  if (isNotificationClick(path)) return initial ? "/" : "";
  return path;
}

export function isNotificationClick(path: string): boolean {
  return /^trackplayer:\/\//i.test(path.trim());
}
