/**
 * API client for the NetGraphy backend.
 */

import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "/api/v1";

export const api = axios.create({
  baseURL: API_BASE,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor: attach auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("netgraphy_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: attempt token refresh on 401, then redirect if that fails
let isRefreshing = false;
let pendingRequests: ((token: string) => void)[] = [];

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const url = originalRequest?.url || "";

    // Never intercept auth endpoints — let login/refresh errors propagate normally
    if (url.includes("/auth/")) {
      return Promise.reject(error);
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      const refreshToken = localStorage.getItem("netgraphy_refresh_token");

      if (!refreshToken) {
        localStorage.removeItem("netgraphy_token");
        window.location.href = "/login";
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(api(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const resp = await api.post("/auth/token", { refresh_token: refreshToken });
        const { access_token, refresh_token: newRefresh } = resp.data.data;

        localStorage.setItem("netgraphy_token", access_token);
        localStorage.setItem("netgraphy_refresh_token", newRefresh);

        pendingRequests.forEach((cb) => cb(access_token));
        pendingRequests = [];

        originalRequest.headers.Authorization = `Bearer ${access_token}`;
        return api(originalRequest);
      } catch {
        localStorage.removeItem("netgraphy_token");
        localStorage.removeItem("netgraphy_refresh_token");
        window.location.href = "/login";
        return Promise.reject(error);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  },
);

// --- Schema ---
export const schemaApi = {
  getUIMetadata: () => api.get("/schema/ui-metadata"),
  getNodeType: (name: string) => api.get(`/schema/node-types/${name}`),
  getEdgeType: (name: string) => api.get(`/schema/edge-types/${name}`),
};

// --- Nodes (dynamic) ---
export const nodesApi = {
  list: (nodeType: string, params?: Record<string, unknown>) =>
    api.get(`/objects/${nodeType}`, { params }),
  get: (nodeType: string, id: string) =>
    api.get(`/objects/${nodeType}/${id}`),
  create: (nodeType: string, data: Record<string, unknown>) =>
    api.post(`/objects/${nodeType}`, data),
  update: (nodeType: string, id: string, data: Record<string, unknown>) =>
    api.patch(`/objects/${nodeType}/${id}`, data),
  delete: (nodeType: string, id: string) =>
    api.delete(`/objects/${nodeType}/${id}`),
  relationships: (nodeType: string, id: string, edgeType?: string) =>
    api.get(`/objects/${nodeType}/${id}/relationships`, {
      params: edgeType ? { edge_type: edgeType } : undefined,
    }),
};

// --- Query ---
export const queryApi = {
  executeCypher: (query: string, parameters?: Record<string, unknown>) =>
    api.post("/query/cypher", { query, parameters }),
  executeStructured: (query: Record<string, unknown>) =>
    api.post("/query/structured", query),
  listSaved: () => api.get("/query/saved"),
  saveQuery: (data: Record<string, unknown>) =>
    api.post("/query/saved", data),
};
