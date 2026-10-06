import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import ProtectedRoute from "./components/ProtectedRoute";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ToastProvider } from "./context/ToastContext";
import DashboardLayout from "./layouts/DashboardLayout";
import AnalyticsPage from "./pages/AnalyticsPage";
import AutomationBuilderPage from "./pages/AutomationBuilderPage"; // NEW (Marketing Automation)
import AutomationDetailPage from "./pages/AutomationDetailPage"; // NEW (Marketing Automation)
import AutomationsPage from "./pages/AutomationsPage"; // NEW (Marketing Automation)
import CampaignCreatePage from "./pages/CampaignCreatePage";
import CampaignDetailPage from "./pages/CampaignDetailPage";
import CampaignEditPage from "./pages/CampaignEditPage";
import CampaignsPage from "./pages/CampaignsPage";
import ContactListsPage from "./pages/ContactListsPage";
import ContactsPage from "./pages/ContactsPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import ScheduledCampaignsPage from "./pages/ScheduledCampaignsPage";
import SegmentsPage from "./pages/SegmentsPage";
import SettingsPage from "./pages/SettingsPage";
import SignupFormsPage from "./pages/SignupFormsPage"; // NEW (Signup Forms feature)
import TagsPage from "./pages/TagsPage";
import TemplateEditorPage from "./pages/TemplateEditorPage";
import TemplatesPage from "./pages/TemplatesPage";

function PublicOnlyRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/dashboard" replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnlyRoute>
            <LoginPage />
          </PublicOnlyRoute>
        }
      />
      <Route
        path="/register"
        element={
          <PublicOnlyRoute>
            <RegisterPage />
          </PublicOnlyRoute>
        }
      />

      <Route
        element={
          <ProtectedRoute>
            <DashboardLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />

        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/contacts/lists" element={<ContactListsPage />} />
        <Route path="/contacts/tags" element={<TagsPage />} />
        <Route path="/contacts/segments" element={<SegmentsPage />} />
        <Route path="/contacts/signup-forms" element={<SignupFormsPage />} /> {/* NEW (Signup Forms feature) */}

        {/* NEW (Marketing Automation) */}
        <Route path="/automations" element={<AutomationsPage />} />
        <Route path="/automations/create" element={<AutomationBuilderPage />} />
        <Route path="/automations/:id" element={<AutomationDetailPage />} />
        <Route path="/automations/:id/edit" element={<AutomationBuilderPage />} />

        <Route path="/templates" element={<TemplatesPage />} />
        <Route path="/templates/create" element={<TemplateEditorPage />} />
        <Route path="/templates/:id/edit" element={<TemplateEditorPage />} />

        <Route path="/campaigns" element={<CampaignsPage />} />
        <Route path="/campaigns/create" element={<CampaignCreatePage />} />
        <Route path="/campaigns/:id" element={<CampaignDetailPage />} />
        <Route path="/campaigns/:id/edit" element={<CampaignEditPage />} />

        <Route path="/scheduled" element={<ScheduledCampaignsPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}