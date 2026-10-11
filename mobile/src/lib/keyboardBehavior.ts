/** KeyboardAvoidingView behavior per platform. Android must not be undefined:
 * SDK 54 apps are always edge-to-edge, so the window no longer resizes for the
 * keyboard (adjustResize is ignored) and the view has to shrink itself. */
export function keyboardAvoidBehavior(os: string): "padding" | "height" {
  return os === "ios" ? "padding" : "height";
}
