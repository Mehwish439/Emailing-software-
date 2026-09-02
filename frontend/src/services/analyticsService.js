import { useSyncExternalStore } from "react";
import api from "./api";

export async function getDashboardSummary() {
  const { data } = await api.get("/analytics/dashboard/");
  return data;
}

export async function getCampaignAnalytics(campaignId) {
  const { data } = await api.get(`/analytics/campaigns/${campaignId}/`);
  return data;
}


