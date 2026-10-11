import { Eye, EyeOff } from "lucide-react-native";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { passkeysAvailable, serverHasPasskeys } from "@/auth/passkey";
import { useAuth } from "@/state/auth";
import { getApiBase, normalizeServerUrl, saveServerUrl, serverFilledFromStamp } from "@/state/config";
import type { LoginError } from "@/state/auth";
import { keyboardAvoidBehavior } from "@/lib/keyboardBehavior";
import { colors, MIN_TOUCH, radius, spacing, typography } from "@/state/theme";
import { HiveWordmark } from "@/ui/HiveWordmark";
import { IconButton } from "@/ui/IconButton";

function messageFor(err: string): string {
  const e = err as LoginError;
  if (e === "invalid_credentials") return "That username or password is incorrect.";
  if (e === "unreachable") return "Can't reach that server. Check the address and your connection.";
  return "Something went wrong signing in. Please try again.";
}

export default function LoginScreen(): React.ReactElement {
  const { signIn, signInWithPasskey } = useAuth();
  const [server, setServer] = useState(getApiBase());
  // Filled in from the server this copy was downloaded from (APK stamp).
  const [prefilled] = useState(() => serverFilledFromStamp() && getApiBase() !== "");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [passkeyBusy, setPasskeyBusy] = useState(false);
  const [serverPasskeys, setServerPasskeys] = useState(false);
  const usernameRef = useRef<TextInput>(null);
  const passwordRef = useRef<TextInput>(null);

  // Offer passkey sign-in only when this device can do it and the typed server
  // has passkeys on (https). Re-checked shortly after the address stops changing.
  const deviceCanPasskey = passkeysAvailable();
  useEffect(() => {
    if (!deviceCanPasskey) return;
    let alive = true;
    setServerPasskeys(false);
    const base = normalizeServerUrl(server);
    if (!base) return;
    const t = setTimeout(() => {
      serverHasPasskeys(base).then((on) => {
        if (alive) setServerPasskeys(on);
      });
    }, 500);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [server, deviceCanPasskey]);
  const showPasskey = deviceCanPasskey && serverPasskeys;

  const onPasskey = useCallback(async () => {
    if (busy || passkeyBusy) return;
    setError(null);
    setPasskeyBusy(true);
    try {
      setServer(await saveServerUrl(server));
      await signInWithPasskey();
    } catch (e) {
      // Fall back to the password form on a cancelled or failed passkey.
      const msg = e instanceof Error ? e.message : "unknown";
      setError(
        msg === "invalid_credentials"
          ? "That passkey isn't registered on this server. Use your password."
          : msg === "unreachable"
            ? messageFor(msg)
            : "Passkey sign-in was cancelled or unavailable. Use your password.",
      );
    } finally {
      setPasskeyBusy(false);
    }
  }, [busy, passkeyBusy, server, signInWithPasskey]);

  const submit = useCallback(async () => {
    if (busy) return;
    setError(null);
    if (!server.trim()) {
      setError("Enter your F7FIVE0 server address.");
      return;
    }
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setBusy(true);
    try {
      setServer(await saveServerUrl(server));
      await signIn(username.trim().toLowerCase(), password);
    } catch (e) {
      setError(messageFor(e instanceof Error ? e.message : "unknown"));
    } finally {
      setBusy(false);
    }
  }, [busy, server, username, password, signIn]);

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={keyboardAvoidBehavior(Platform.OS)} style={styles.flex}>
        <ScrollView
          contentContainerStyle={styles.center}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.logo}>
            <HiveWordmark height={40} />
          </View>
          <Text style={styles.subtitle}>Sign in to your library</Text>

          <TextInput
            style={styles.input}
            placeholder="Server, e.g. 192.168.1.20:3001"
            placeholderTextColor={colors.textFaint}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            value={server}
            onChangeText={setServer}
            returnKeyType="next"
            onSubmitEditing={() => usernameRef.current?.focus()}
            accessibilityLabel="Server"
          />
          {prefilled && normalizeServerUrl(server) === getApiBase() ? (
            <Text style={styles.hint}>Filled in from the server you downloaded the app from.</Text>
          ) : null}

          {showPasskey ? (
            <>
              <Pressable
                onPress={onPasskey}
                disabled={passkeyBusy || busy}
                accessibilityRole="button"
                accessibilityLabel="Sign in with passkey"
                style={({ pressed }) => [
                  styles.passkeyButton,
                  pressed && styles.passkeyButtonPressed,
                  (passkeyBusy || busy) && styles.buttonBusy,
                ]}
              >
                {passkeyBusy ? (
                  <ActivityIndicator color={colors.accent} />
                ) : (
                  <Text style={styles.passkeyButtonText}>Sign in with passkey</Text>
                )}
              </Pressable>

              <View style={styles.dividerRow}>
                <View style={styles.dividerLine} />
                <Text style={styles.dividerText}>or use your password</Text>
                <View style={styles.dividerLine} />
              </View>
            </>
          ) : null}

          <TextInput
            ref={usernameRef}
            style={styles.input}
            placeholder="Username"
            placeholderTextColor={colors.textFaint}
            autoCapitalize="none"
            autoCorrect={false}
            value={username}
            onChangeText={setUsername}
            returnKeyType="next"
            onSubmitEditing={() => passwordRef.current?.focus()}
            accessibilityLabel="Username"
          />

          <View style={styles.passwordRow}>
            <TextInput
              ref={passwordRef}
              style={styles.passwordInput}
              placeholder="Password"
              placeholderTextColor={colors.textFaint}
              secureTextEntry={!showPassword}
              value={password}
              onChangeText={setPassword}
              returnKeyType="go"
              onSubmitEditing={submit}
              accessibilityLabel="Password"
            />
            <IconButton
              icon={showPassword ? EyeOff : Eye}
              onPress={() => setShowPassword((v) => !v)}
              accessibilityLabel={showPassword ? "Hide password" : "Show password"}
              color={colors.textMuted}
            />
          </View>

          {error ? (
            <Text style={styles.error} accessibilityLiveRegion="polite">
              {error}
            </Text>
          ) : null}

          <Pressable
            onPress={submit}
            disabled={busy || passkeyBusy}
            accessibilityRole="button"
            accessibilityLabel="Sign in"
            style={({ pressed }) => [styles.button, pressed && styles.buttonPressed, busy && styles.buttonBusy]}
          >
            {busy ? (
              <ActivityIndicator color={colors.onHive} />
            ) : (
              <Text style={styles.buttonText}>Sign in</Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  center: { flexGrow: 1, justifyContent: "center", padding: spacing.xl, gap: spacing.md },
  logo: { alignItems: "center", marginBottom: spacing.sm },
  subtitle: { ...typography.body, color: colors.textMuted, textAlign: "center", marginBottom: spacing.lg },
  hint: { ...typography.caption, color: colors.textFaint, marginTop: -spacing.xs, paddingHorizontal: spacing.xs },
  input: {
    minHeight: MIN_TOUCH + 6,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
    color: colors.text,
    fontSize: 16,
  },
  passwordRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    paddingRight: spacing.xs,
  },
  passwordInput: {
    flex: 1,
    minHeight: MIN_TOUCH + 6,
    paddingHorizontal: spacing.lg,
    color: colors.text,
    fontSize: 16,
  },
  error: { ...typography.body, color: colors.danger, textAlign: "center" },
  button: {
    minHeight: MIN_TOUCH + 4,
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    marginTop: spacing.sm,
  },
  buttonPressed: { backgroundColor: colors.accentPressed },
  buttonBusy: { opacity: 0.8 },
  // White on hive red (design system on-hive); the old dark label was unreadable.
  buttonText: { color: colors.onHive, fontWeight: "700", fontSize: 16 },
  passkeyButton: {
    minHeight: MIN_TOUCH + 4,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  passkeyButtonPressed: { backgroundColor: colors.surface },
  passkeyButtonText: { color: colors.accent, fontWeight: "700", fontSize: 16 },
  dividerRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dividerLine: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: colors.border },
  dividerText: { ...typography.caption, color: colors.textFaint },
});
