// NEW FILE (Marketing Automation feature)
import api from "./api";

export async function listAutomations(params = {}) {
  const { data } = await api.get("/automations/", { params });
  return data;
}

export async function getAutomation(id) {
  const { data } = await api.get(`/automations/${id}/`);
  return data;
}

export async function createAutomation(payload) {
  const { data } = await api.post("/automations/", payload);
  return data;
}

export async function updateAutomation(id, payload) {
  const { data } = await api.patch(`/automations/${id}/`, payload);
  return data;
}

export async function deleteAutomation(id) {
  await api.delete(`/automations/${id}/`);
}

export async function activateAutomation(id) {
  const { data } = await api.post(`/automations/${id}/activate/`);
  return data;
}

export async function pauseAutomation(id) {
  const { data } = await api.post(`/automations/${id}/pause/`);
  return data;
}

export async function resumeAutomation(id) {
  const { data } = await api.post(`/automations/${id}/resume/`);
  return data;
}

export async function enrollContacts(id, contactIds) {
  const { data } = await api.post(`/automations/${id}/enroll/`, { contact_ids: contactIds });
  return data;
}

export async function getAutomationStats(id) {
  const { data } = await api.get(`/automations/${id}/stats/`);
  return data;
}

export async function getAutomationLogs(id, params = {}) {
  const { data } = await api.get(`/automations/${id}/logs/`, { params });
  return data;
}

export async function getAutomationEnrollments(id, params = {}) {
  const { data } = await api.get(`/automations/${id}/enrollments/`, { params });
  return data;
}
