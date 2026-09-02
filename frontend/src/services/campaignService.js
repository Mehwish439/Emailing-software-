import api from "./api";

export async function listCampaigns(params = {}) {
  const { data } = await api.get("/campaigns/", { params });
  return data;
}

export async function getCampaign(id) {
  const { data } = await api.get(`/campaigns/${id}/`);
  return data;
}

export async function createCampaign(payload) {
  const { data } = await api.post("/campaigns/", payload);
  return data;
}

export async function updateCampaign(id, payload) {
  const { data } = await api.patch(`/campaigns/${id}/`, payload);
  return data;
}

export async function deleteCampaign(id) {
  await api.delete(`/campaigns/${id}/`);
}

export async function duplicateCampaign(id) {
  const { data } = await api.post(`/campaigns/${id}/duplicate/`);
  return data;
}

export async function previewCampaign(id) {
  const { data } = await api.get(`/campaigns/${id}/preview/`);
  return data;
}

export async function sendTestEmail(id, testEmail) {
  const { data } = await api.post(`/campaigns/${id}/test/`, { test_email: testEmail });
  return data;
}

export async function sendCampaignNow(id) {
  const { data } = await api.post(`/campaigns/${id}/send-now/`);
  return data;
}

export async function getCampaignStatistics(id) {
  const { data } = await api.get(`/campaigns/${id}/statistics/`);
  return data;
}

export async function getCampaignRecipients(id, params = {}) {
  const { data } = await api.get(`/campaigns/${id}/recipients/`, { params });
  return data;
}
