// Maps a stat-card label to the recipient status value(s) — comma-joined,
// matching CampaignRecipient.Status on the backend — used to filter the
// recipients list when that card is clicked. Shared between DashboardPage
// and AnalyticsPage so both pages' "click a stat to see matching
// recipients" behavior follows the same rules as CampaignDetailPage's
// original version of this interaction (e.g. "Delivered" also includes
// recipients who progressed further to opened/clicked, since they were
// still delivered).
export const RECIPIENT_STATUS_FILTERS = {
  "Emails Sent": "sent,delivered,opened,clicked,bounced,blocked,unsubscribed,spam,failed",
  Delivered: "delivered,opened,clicked",
  Opened: "opened,clicked",
  Clicked: "clicked",
  Bounced: "bounced",
  Unsubscribed: "unsubscribed",
  "Spam Complaints": "spam",
};
