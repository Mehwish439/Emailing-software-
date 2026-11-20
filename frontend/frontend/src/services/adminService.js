import api from "./api";

const get = async (url, params) => (await api.get(url, { params })).data;
const post = async (url, body) => (await api.post(url, body ?? {})).data;
const patch = async (url, body) => (await api.patch(url, body)).data;

// ---- Company admin (/api/company/*) — the backend scopes everything to the caller's own company ----
export const company = {
  overview: () => get("/company/overview/"),
  members: (params) => get("/company/members/", params),
  invite: (body) => post("/company/members/", body),
  resendInvite: (id) => post(`/company/members/${id}/resend-invite/`),
  updateMember: (id, body) => patch(`/company/members/${id}/`, body),
  memberCampaigns: (id, action) => post(`/company/members/${id}/campaigns/${action}/`),
  quotas: () => get("/company/quotas/"),
  campaigns: (params) => get("/company/campaigns/", params),
  campaignAction: (id, action) => post(`/company/campaigns/${id}/${action}/`),
  analytics: (params) => get("/company/analytics/", params),
  suppressions: (params) => get("/company/suppressions/", params),
  audit: (params) => get("/company/audit-log/", params),
  settings: () => get("/company/settings/"),
  updateSettings: (body) => patch("/company/settings/", body),
  subscription: () => get("/company/subscription/"),
};

// ---- Platform super admin (/api/platform/*) ----
export const platform = {
  overview: () => get("/platform/overview/"),
  companies: (params) => get("/platform/companies/", params),
  company: (id) => get(`/platform/companies/${id}/`),
  createCompany: (body) => post("/platform/companies/", body),
  updateCompany: (id, body) => patch(`/platform/companies/${id}/`, body),
  companyAction: (id, action, body) => post(`/platform/companies/${id}/${action}/`, body),
  inviteMember: (companyId, body) => post(`/platform/companies/${companyId}/members/`, body),
  users: (params) => get("/platform/users/", params),
  userAction: (id, action) => post(`/platform/users/${id}/${action}/`),
  plans: () => get("/platform/plans/"),
  createPlan: (body) => post("/platform/plans/", body),
  updatePlan: (id, body) => patch(`/platform/plans/${id}/`, body),
  planAction: (id, action) => post(`/platform/plans/${id}/${action}/`),
  settings: () => get("/platform/settings/"),
  updateSettings: (body) => patch("/platform/settings/", body),
  quotas: () => get("/platform/quotas/"),
  queue: () => get("/platform/queue/"),
  setQueuePaused: (paused) => post("/platform/queue/", { paused }),
  queueMessages: (params) => get("/platform/queue/messages/", params),
  messageAction: (id, action, body) => post(`/platform/queue/messages/${id}/${action}/`, body),
  campaigns: (params) => get("/platform/campaigns/", params),
  campaignAction: (id, action, body) => post(`/platform/campaigns/${id}/${action}/`, body),
  health: (params) => get("/platform/health/", params),
  audit: (params) => get("/platform/audit-log/", params),
  analytics: (params) => get("/platform/analytics/", params),
};

// ---- Public invitation flow ----
export const acceptInvite = (token, password, extra = {}) => post("/auth/accept-invite/", { token, password, ...extra });
