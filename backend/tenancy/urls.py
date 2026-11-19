from django.urls import path

from . import views_company as c
from . import views_platform as p

urlpatterns = [
    # ---- company admin ----
    path("company/overview/", c.Overview.as_view()),
    path("company/members/", c.Members.as_view()),
    path("company/members/<int:pk>/", c.MemberDetail.as_view()),
    path("company/members/<int:pk>/resend-invite/", c.ResendInvite.as_view()),
    path("company/members/<int:pk>/campaigns/<str:action>/", c.MemberCampaignAction.as_view()),
    path("company/quotas/", c.Quotas.as_view()),
    path("company/campaigns/", c.CompanyCampaigns.as_view()),
    path("company/campaigns/<int:pk>/<str:action>/", c.CompanyCampaignAction.as_view()),
    path("company/analytics/", c.CompanyAnalytics.as_view()),
    path("company/suppressions/", c.CompanySuppressions.as_view()),
    path("company/audit-log/", c.CompanyAudit.as_view()),
    path("company/settings/", c.CompanySettings.as_view()),
    path("company/subscription/", c.Subscription.as_view()),
    # ---- platform super admin ----
    path("platform/overview/", p.Overview.as_view()),
    path("platform/companies/", p.Companies.as_view()),
    path("platform/companies/<int:pk>/", p.CompanyDetail.as_view()),
    path("platform/companies/<int:pk>/members/", p.CompanyMembersInvite.as_view()),
    path("platform/companies/<int:pk>/<str:action>/", p.CompanyStatus.as_view()),
    path("platform/users/", p.Users.as_view()),
    path("platform/users/<int:pk>/<str:action>/", p.UserAction.as_view()),
    path("platform/plans/", p.Plans.as_view()),
    path("platform/plans/<int:pk>/", p.PlanDetail.as_view()),
    path("platform/plans/<int:pk>/<str:action>/", p.PlanAction.as_view()),
    path("platform/settings/", p.SettingsView.as_view()),
    path("platform/quotas/", p.QuotaOverview.as_view()),
    path("platform/queue/", p.Queue.as_view()),
    path("platform/queue/messages/", p.QueueMessages.as_view()),
    path("platform/queue/messages/<int:pk>/<str:action>/", p.QueueMessageAction.as_view()),
    path("platform/campaigns/", p.MonitorCampaigns.as_view()),
    path("platform/campaigns/<int:pk>/<str:action>/", p.CampaignAction.as_view()),
    path("platform/health/", p.Health.as_view()),
    path("platform/audit-log/", p.PlatformAudit.as_view()),
    path("platform/analytics/", p.Analytics.as_view()),
]
