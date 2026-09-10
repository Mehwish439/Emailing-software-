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

export async function downloadAllCampaignsReportPdf() {
  const response = await api.get("/analytics/report.pdf", { responseType: "blob" });
  downloadBlob(response.data, "campaigns-report.pdf");
}