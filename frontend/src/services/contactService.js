import api from "./api";

export async function listContacts(params = {}) {
  const { data } = await api.get("/contacts/", { params });
  return data;
}

export async function createContact(payload) {
  const { data } = await api.post("/contacts/", payload);
  return data;
}

export async function updateContact(id, payload) {
  const { data } = await api.patch(`/contacts/${id}/`, payload);
  return data;
}

export async function deleteContact(id) {
  await api.delete(`/contacts/${id}/`);
}

export async function bulkDeleteContacts(ids) {
  const { data } = await api.post("/contacts/bulk-delete/", { ids });
  return data;
}

export async function getMergeFields() {
  const { data } = await api.get("/contacts/merge-fields/");
  return data;
}

export async function importContactsCSV(file, listIds = []) {
  const formData = new FormData();
  formData.append("file", file);
  listIds.forEach((id) => formData.append("list_ids", id));
  const { data } = await api.post("/contacts/import-csv/", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function addContactsToList(listId, contactIds) {
  const { data } = await api.post("/contacts/add-to-list/", { list_id: listId, contact_ids: contactIds });
  return data;
}

export async function removeContactsFromList(listId, contactIds) {
  const { data } = await api.post("/contacts/remove-from-list/", { list_id: listId, contact_ids: contactIds });
  return data;
}

export async function listContactLists(params = {}) {
  const { data } = await api.get("/contact-lists/", { params });
  return data;
}

export async function createContactList(payload) {
  const { data } = await api.post("/contact-lists/", payload);
  return data;
}

export async function updateContactList(id, payload) {
  const { data } = await api.patch(`/contact-lists/${id}/`, payload);
  return data;
}

export async function deleteContactList(id) {
  await api.delete(`/contact-lists/${id}/`);
}