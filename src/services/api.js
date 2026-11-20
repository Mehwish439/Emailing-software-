import axios from "axios";

// The backend serves everything under /api. A base URL written without it (e.g. http://localhost:8000)
// would turn every call into a 404, so normalise: trim, drop trailing slashes, ensure the /api suffix.
function normalizeApiBase(raw) {
  const base = (raw || "http://localhost:8000/api").trim().replace(/\/+$/, "");
  return /\/api$/.test(base) ? base : `${base}/api`;
}
export const API_BASE_URL = normalizeApiBase(import.meta.env.VITE_API_BASE_URL);

// Public endpoints: never send a (possibly stale/expired) Bearer token to them. DRF would reject an invalid
// token with 401 even though these views allow anonymous access, which broke sign-up/login after a session expired.
const PUBLIC_PATHS = ["/auth/login", "/auth/register", "/auth/register-company", "/auth/refresh", "/auth/forgot-password", "/auth/accept-invite", "/auth/invite-info"];
const isPublic = (url = "") => PUBLIC_PATHS.some((p) => url.includes(p));

const api = axios.create({
  baseURL: API_BASE_URL,
});

export function getAccessToken() {
  return localStorage.getItem("access_token");
}

export function getRefreshToken() {
  return localStorage.getItem("refresh_token");
}

export function setTokens({ access, refresh }) {
  if (access) localStorage.setItem("access_token", access);
  if (refresh) localStorage.setItem("refresh_token", refresh);
}

export function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token && !isPublic(config.url)) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let isRefreshing = false;
let pendingQueue = [];

function processQueue(error, token = null) {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token);
  });
  pendingQueue = [];
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const isAuthEndpoint = isPublic(originalRequest?.url);
    // Treat 401 and 403 identically here. With CustomJWTAuthentication on the
    // backend (accounts/authentication.py), an expired/missing/invalid token
    // should always come back as 401 — but 403 is included too as a safety
    // net, since this app has no legitimate per-resource 403 (ownership
    // filtering returns 404, not 403, for other users' data) and a stray 403
    // slipping past this check would otherwise leave the UI silently broken
    // instead of refreshing the token or redirecting to login.
    // 401 = expired/invalid token. A 403 only counts as an auth failure when the backend says credentials
    // were missing/invalid; a genuine permission denial (e.g. a company admin calling /platform/*) must NOT
    // force a refresh or log the user out.
    const detailText = JSON.stringify(error.response?.data?.detail ?? "").toLowerCase();
    const isAuthFailure =
      error.response?.status === 401 ||
      (error.response?.status === 403 && /credentials|token not valid|not authenticated/.test(detailText));

    if (isAuthFailure && !originalRequest._retry && !isAuthEndpoint) {
      const refresh = getRefreshToken();
      if (!refresh) {
        clearTokens();
        window.location.href = "/login?expired=1";
        return Promise.reject(error);
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const { data } = await axios.post(`${API_BASE_URL}/auth/refresh/`, { refresh });
        setTokens({ access: data.access });
        processQueue(null, data.access);
        originalRequest.headers.Authorization = `Bearer ${data.access}`;
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        clearTokens();
        window.location.href = "/login?expired=1";
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default api;
