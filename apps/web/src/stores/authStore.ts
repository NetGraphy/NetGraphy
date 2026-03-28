/**
 * Auth Store — manages authentication state, tokens, and user profile.
 *
 * Tokens are persisted in localStorage and attached to API requests
 * via the interceptor in api/client.ts.
 */

import { create } from "zustand";
import { api } from "@/api/client";

interface User {
  id: string;
  username: string;
  email: string;
  role: string;
}

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  loading: boolean;

  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  refreshAuth: () => Promise<void>;
  loadFromStorage: () => void;
}

const TOKEN_KEY = "netgraphy_token";
const REFRESH_TOKEN_KEY = "netgraphy_refresh_token";

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  refreshToken: null,
  user: null,
  isAuthenticated: false,
  loading: false,

  login: async (username: string, password: string) => {
    set({ loading: true });
    try {
      const response = await api.post("/auth/login", { username, password });
      const { access_token, refresh_token } = response.data.data;

      localStorage.setItem(TOKEN_KEY, access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token);

      set({
        token: access_token,
        refreshToken: refresh_token,
        isAuthenticated: true,
      });

      // Fetch user profile
      const profileResponse = await api.get("/auth/me");
      set({ user: profileResponse.data.data, loading: false });
    } catch (err) {
      set({ loading: false });
      throw err;
    }
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    set({
      token: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
    });
  },

  refreshAuth: async () => {
    const { refreshToken } = get();
    if (!refreshToken) return;

    try {
      const response = await api.post("/auth/token", {
        refresh_token: refreshToken,
      });
      const { access_token, refresh_token } = response.data.data;

      localStorage.setItem(TOKEN_KEY, access_token);
      localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token);

      set({
        token: access_token,
        refreshToken: refresh_token,
        isAuthenticated: true,
      });
    } catch {
      // Refresh failed — force logout
      get().logout();
    }
  },

  loadFromStorage: () => {
    const token = localStorage.getItem(TOKEN_KEY);
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);

    if (token) {
      set({
        token,
        refreshToken,
        isAuthenticated: true,
        loading: true,
      });

      // Fetch user profile in the background
      api
        .get("/auth/me")
        .then((response) => {
          set({ user: response.data.data, loading: false });
        })
        .catch(() => {
          // Token might be expired — try refresh
          if (refreshToken) {
            get()
              .refreshAuth()
              .then(() => {
                return api.get("/auth/me");
              })
              .then((response) => {
                set({ user: response.data.data, loading: false });
              })
              .catch(() => {
                get().logout();
                set({ loading: false });
              });
          } else {
            get().logout();
            set({ loading: false });
          }
        });
    }
  },
}));
