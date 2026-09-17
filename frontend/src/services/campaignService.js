import api from "./api";
import { downloadBlob, slugify } from "../utils/download";

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

export async function sendTestEmail(id, testEmail, variant) {
  const payload = { test_email: testEmail };
  if (variant) payload.variant = variant;
  const { data } = await api.post(`/campaigns/${id}/test/`, payload);
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

// -- A/B Testing --------------------------------------------------------

export async function getCampaignVariants(id) {
  const { data } = await api.get(`/campaigns/${id}/ab-variants/`);
  return data;
}

export async function setCampaignVariants(id, variants) {
  const { data } = await api.put(`/campaigns/${id}/ab-variants/`, { variants });
  return data;
}

export async function getCampaignAbResults(id) {
  const { data } = await api.get(`/campaigns/${id}/ab-results/`);
  return data;
}

export async function previewCampaignVariant(id, variant) {
  const { data } = await api.get(`/campaigns/${id}/preview/`, { params: { variant } });
  return data;
}

export async function downloadCampaignReportPdf(id, campaignName) {
  const response = await api.get(`/analytics/campaigns/${id}/report.pdf`, { responseType: "blob" });
  downloadBlob(response.data, `${slugify(campaignName)}-report.pdf`);
}