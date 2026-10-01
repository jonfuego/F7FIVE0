/** Token storage contract and the expo-secure-store implementation.
 *
 * Security rule (criterion 15): ONLY the refresh token is ever persisted, and
 * only in the OS keystore via expo-secure-store. The access token lives in
 * memory in the API client and is never written to SecureStore or AsyncStorage.
 */
import * as SecureStore from "expo-secure-store";

// The single key SecureStore.setItemAsync is ever called with.
export const REFRESH_TOKEN_KEY = "f7five0.refresh_token";

export interface TokenStore {
  getRefresh(): Promise<string | null>;
  setRefresh(token: string): Promise<void>;
  clear(): Promise<void>;
}

export const secureTokenStore: TokenStore = {
  async getRefresh() {
    return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
  },
  async setRefresh(token: string) {
    // Only ever the refresh token. The access token stays in memory.
    await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token);
  },
  async clear() {
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  },
};
