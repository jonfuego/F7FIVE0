import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ApiClient, ApiError, AuthError, NetworkError, createApiClient } from "@/api/client";
import { secureTokenStore } from "@/api/tokenStore";
import { passkeyLogin } from "@/auth/passkey";
import { APP_VERSION, clientPlatform, deviceName, getApiBase } from "./config";

type AuthStatus = "loading" | "signedOut" | "signedIn";

export type LoginError = "invalid_credentials" | "unreachable" | "unknown";

interface AuthContextValue {
  status: AuthStatus;
  client: ApiClient;
  signIn: (username: string, password: string) => Promise<void>;
  signInWithPasskey: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  // Ref so the client's onLogout callback always sees the latest setter.
  const setStatusRef = useRef(setStatus);
  setStatusRef.current = setStatus;

  const client = useMemo(
    () =>
      createApiClient({
        baseUrl: getApiBase,
        tokenStore: secureTokenStore,
        onLogout: () => setStatusRef.current("signedOut"),
        clientMeta: {
          device_name: deviceName(),
          platform: clientPlatform(),
          client_version: APP_VERSION,
        },
      }),
    [],
  );

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const ok = await client.bootstrap();
        if (active) setStatus(ok ? "signedIn" : "signedOut");
      } catch {
        // Network error at launch: we have a refresh token but can't reach the
        // server. Treat as signed-in-offline so we don't wrongly kick to login.
        if (active) setStatus("signedIn");
      }
    })();
    return () => {
      active = false;
    };
  }, [client]);

  const signIn = useCallback(
    async (username: string, password: string) => {
      try {
        await client.login(username, password);
        setStatus("signedIn");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          const err: LoginError = "invalid_credentials";
          throw new Error(err);
        }
        if (e instanceof NetworkError) {
          const err: LoginError = "unreachable";
          throw new Error(err);
        }
        const err: LoginError = "unknown";
        throw new Error(err);
      }
    },
    [client],
  );

  const signInWithPasskey = useCallback(async () => {
    try {
      const pair = await passkeyLogin();
      await client.adoptSession(pair);
      setStatus("signedIn");
    } catch (e) {
      if (e instanceof Error && e.message === "invalid_passkey") {
        const err: LoginError = "invalid_credentials";
        throw new Error(err);
      }
      if (e instanceof TypeError) {
        // fetch() rejects with TypeError when the server can't be reached.
        const err: LoginError = "unreachable";
        throw new Error(err);
      }
      // A cancelled prompt lands here; the login screen falls back to the
      // password form.
      const err: LoginError = "unknown";
      throw new Error(err);
    }
  }, [client]);

  const signOut = useCallback(async () => {
    try {
      await client.logout();
    } catch {
      // ignore; local state is cleared regardless
    }
    setStatus("signedOut");
  }, [client]);

  const value = useMemo<AuthContextValue>(
    () => ({ status, client, signIn, signInWithPasskey, signOut }),
    [status, client, signIn, signInWithPasskey, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function useApi(): ApiClient {
  return useAuth().client;
}

export { AuthError };
