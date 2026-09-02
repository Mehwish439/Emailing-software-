import api, { clearTokens, setTokens } from "./api";

export async function register(payload) {
  const { data } = await api.post("/auth/register/", payload);
  setTokens({ access: data.access, refresh: data.refresh });
  return data.user;
}

export async function login({ username, password }) {
  const { data } = await api.post("/auth/login/", { username, password });
  setTokens({ access: data.access, refresh: data.refresh });
  return data.user;
}

export async function logout() {
  const refresh = localStorage.getItem("refresh_token");
  try {
    if (refresh) await api.post("/auth/logout/", { refresh });
  } finally {
    clearTokens();
  }
}

export async function fetchCurrentUser() {
  const { data } = await api.get("/auth/me/");
  return data;
}

export async function updateProfile(payload) {
  const { data } = await api.patch("/auth/me/", payload);
  return data;
}
