import api from "./api";

export async function listScheduledCampaigns() {
  const { data } = await api.get("/scheduling/");
  return data;
}

export async function createSchedule(payload) {
  const { data } = await api.post("/scheduling/schedule/", payload);
  return data;
}

export async function updateSchedule(id, payload) {
  const { data } = await api.put(`/scheduling/${id}/`, payload);
  return data;
}

export async function cancelSchedule(id) {
  await api.delete(`/scheduling/${id}/`);
}
