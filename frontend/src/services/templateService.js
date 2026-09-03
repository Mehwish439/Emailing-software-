import api from "./api";

export async function listTemplates(params = {}) {
  const { data } = await api.get("/templates/", { params });
  return data;
}

export async function getTemplate(id) {
  const { data } = await api.get(`/templates/${id}/`);
  return data;
}

export async function createTemplate(payload) {
  const { data } = await api.post("/templates/", payload);
  return data;
}

export async function updateTemplate(id, payload) {
  const { data } = await api.patch(`/templates/${id}/`, payload);
  return data;
}

export async function deleteTemplate(id) {
  await api.delete(`/templates/${id}/`);
}

export async function duplicateTemplate(id) {
  const { data } = await api.post(`/templates/${id}/duplicate/`);
  return data;
}

export async function previewTemplate(id) {
  const { data } = await api.get(`/templates/${id}/preview/`);
  return data;
}

export async function listStarterTemplates() {
  const { data } = await api.get("/templates/starters/");
  return data;
}

export async function uploadTemplateImage(file, onUploadProgress) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await api.post("/templates/images/", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress,
  });
  return data;
}