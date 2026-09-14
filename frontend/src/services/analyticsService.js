import { useSyncExternalStore } from "react";
import api from "./api";
import { downloadBlob } from "../utils/download";

export async function getDashboardSummary() {
  const { data } = await api.get("/analytics/dashboard/");
  return data;
}

export async function getCampaignAnalytics(campaignId) {
  const { data } = await api.get(`/analytics/campaigns/${campaignId}/`);
  return data;
}

// Cross-campaign recipients list, used by the Dashboard and Analytics
// pages' clickable stat cards (see RECIPIENT_STATUS_FILTERS) — unlike
// campaignService.getCampaignRecipients, this isn't scoped to one
// campaign. Pass `campaign` to restrict to a single one anyway (used by
// AnalyticsPage while a specific campaign is selected there).
export async function getAllRecipients(params = {}) {
  const { data } = await api.get("/analytics/recipients/", { params });
  return data;
}

export async function downloadAllCampaignsReportPdf() {
  const response = await api.get("/analytics/report.pdf", { responseType: "blob" });
  downloadBlob(response.data, "campaigns-report.pdf");
}