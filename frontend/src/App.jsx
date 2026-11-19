import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import ProtectedRoute from "./components/ProtectedRoute";
import RoleRoute from "./components/RoleRoute";
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
import ScheduledCampaignsPage from "./pages/ScheduledCampaignsPage";
import SegmentsPage from "./pages/SegmentsPage";
import SettingsPage from "./pages/SettingsPage";
import SignupFormsPage from "./pages/SignupFormsPage"; // NEW (Signup Forms feature)
import TagsPage from "./pages/TagsPage";
import TemplateEditorPage from "./pages/TemplateEditorPage";
import TemplatesPage from "./pages/TemplatesPage";
import AcceptInvitePage from "./pages/AcceptInvitePage";
import SignUpPage from "./pages/SignUpPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import CompanyAnalytics from "./pages/company/CompanyAnalytics";
import CompanyAudit from "./pages/company/CompanyAudit";
import CompanyCampaigns from "./pages/company/CompanyCampaigns";
import CompanyMembers from "./pages/company/CompanyMembers";
import CompanyOverview from "./pages/company/CompanyOverview";
import CompanyQuotas from "./pages/company/CompanyQuotas";
import CompanySettings from "./pages/company/CompanySettings";
import CompanySuppressions from "./pages/company/CompanySuppressions";
import PlatformAnalytics from "./pages/platform/PlatformAnalytics";
import PlatformAudit from "./pages/platform/PlatformAudit";
import PlatformCampaigns from "./pages/platform/PlatformCampaigns";
import PlatformCompanies from "./pages/platform/PlatformCompanies";
import PlatformCompanyDetail from "./pages/platform/PlatformCompanyDetail";
import PlatformHealth from "./pages/platform/PlatformHealth";
import PlatformOverview from "./pages/platform/PlatformOverview";
import PlatformPlans from "./pages/platform/PlatformPlans";
import PlatformProviders from "./pages/platform/PlatformProviders";
import PlatformQueue from "./pages/platform/PlatformQueue";
import PlatformUsers from "./pages/platform/PlatformUsers";
import { homePathFor, isCompanyAdmin, isPlatformAdmin } from "./utils/roles";

function PublicOnlyRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to={homePathFor(user)} replace />;
  return children;
}

function HomeRedirect() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return <Navigate to={user ? homePathFor(user) : "/login"} replace />;
}

const companyOnly = (el) => <RoleRoute allow={isCompanyAdmin}>{el}</RoleRoute>;
const platformOnly = (el) => <RoleRoute allow={isPlatformAdmin}>{el}</RoleRoute>;

function AppRoutes() {
  return (
    <Routes>
      <Route path="/accept-invite" element={<AcceptInvitePage />} />
      <Route path="/join" element={<AcceptInvitePage />} />
      <Route path="/signup" element={<PublicOnlyRoute><SignUpPage /></PublicOnlyRoute>} />
      {/* Friendly aliases for the dashboards (canonical routes are /company and /platform) */}
      <Route path="/company-admin/*" element={<Navigate to="/company" replace />} />
      <Route path="/saas-admin/*" element={<Navigate to="/platform" replace />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route
        path="/login"
        element={
          <PublicOnlyRoute>
            <LoginPage />
          </PublicOnlyRoute>
        }
      />
      <Route path="/register" element={<Navigate to="/signup" replace />} />

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

        {/* Company admin dashboard (backend scopes every call to the caller's own company) */}
        <Route path="/company" element={companyOnly(<CompanyOverview />)} />
        <Route path="/company/members" element={companyOnly(<CompanyMembers />)} />
        <Route path="/company/quotas" element={companyOnly(<CompanyQuotas />)} />
        <Route path="/company/campaigns" element={companyOnly(<CompanyCampaigns />)} />
        <Route path="/company/analytics" element={companyOnly(<CompanyAnalytics />)} />
        <Route path="/company/suppressions" element={companyOnly(<CompanySuppressions />)} />
        <Route path="/company/audit" element={companyOnly(<CompanyAudit />)} />
        <Route path="/company/settings" element={companyOnly(<CompanySettings />)} />

        {/* Platform super-admin dashboard */}
        <Route path="/platform" element={platformOnly(<PlatformOverview />)} />
        <Route path="/platform/companies" element={platformOnly(<PlatformCompanies />)} />
        <Route path="/platform/companies/:id" element={platformOnly(<PlatformCompanyDetail />)} />
        <Route path="/platform/users" element={platformOnly(<PlatformUsers />)} />
        <Route path="/platform/plans" element={platformOnly(<PlatformPlans />)} />
        <Route path="/platform/providers" element={platformOnly(<PlatformProviders />)} />
        <Route path="/platform/queue" element={platformOnly(<PlatformQueue />)} />
        <Route path="/platform/campaigns" element={platformOnly(<PlatformCampaigns />)} />
        <Route path="/platform/analytics" element={platformOnly(<PlatformAnalytics />)} />
        <Route path="/platform/health" element={platformOnly(<PlatformHealth />)} />
        <Route path="/platform/audit" element={platformOnly(<PlatformAudit />)} />
      </Route>

      <Route path="/" element={<HomeRedirect />} />
      <Route path="*" element={<HomeRedirect />} />
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