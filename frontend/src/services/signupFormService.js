// NEW FILE (Signup Forms feature)
import api from "./api";

export async function listSignupForms(params = {}) {
  const { data } = await api.get("/signup-forms/", { params });
  return data;
}

export async function createSignupForm(payload) {
  const { data } = await api.post("/signup-forms/", payload);
  return data;
}

export async function updateSignupForm(id, payload) {
  const { data } = await api.patch(`/signup-forms/${id}/`, payload);
  return data;
}

export async function deleteSignupForm(id) {
  await api.delete(`/signup-forms/${id}/`);
}
