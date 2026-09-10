"""
Numbers-only PDF exports for campaign analytics — deliberately just the
summary counts/rates (Sent, Delivered, Opened, ...), never a per-recipient
log dump. Uses reportlab (pure-Python, no system-level dependencies like
Cairo/Pango), which keeps this safe to run on Render without extra native
packages.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_STYLES = getSampleStyleSheet()

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b47dd")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
)


def build_campaign_report_pdf(campaign, analytics):
    """
    One campaign's number breakdown (counts + rates) — matches what's shown
    on its detail/analytics page, just as a downloadable PDF instead.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    elements = [
        Paragraph(campaign.name, _STYLES["Title"]),
        Paragraph(campaign.subject, _STYLES["Normal"]),
        Spacer(1, 4),
        Paragraph(
            f"Status: {campaign.get_status_display()}"
            + (f" &nbsp;&bull;&nbsp; Sent: {campaign.sent_at.strftime('%b %d, %Y %H:%M')}" if campaign.sent_at else ""),
            _STYLES["Normal"],
        ),
        Spacer(1, 18),
    ]

    counts_table = Table(
        [
            ["Metric", "Count"],
            ["Sent", analytics["sent"]],
            ["Delivered", analytics["delivered"]],
            ["Opened", analytics["opened"]],
            ["Clicked", analytics["clicked"]],
            ["Soft bounced", analytics["soft_bounced"]],
            ["Hard bounced", analytics["hard_bounced"]],
            ["Blocked", analytics["blocked"]],
            ["Unsubscribed", analytics["unsubscribed"]],
            ["Spam complaints", analytics["spam"]],
        ],
        colWidths=[3 * inch, 2 * inch],
    )
    counts_table.setStyle(_TABLE_STYLE)
    elements.append(counts_table)
    elements.append(Spacer(1, 24))

    rates_table = Table(
        [
            ["Rate", "Value"],
            ["Delivery rate", f"{analytics['delivery_rate']}%"],
            ["Open rate", f"{analytics['open_rate']}%"],
            ["Click rate", f"{analytics['click_rate']}%"],
            ["Bounce rate", f"{analytics['bounce_rate']}%"],
            ["Unsubscribe rate", f"{analytics['unsubscribe_rate']}%"],
            ["Spam rate", f"{analytics['spam_rate']}%"],
        ],
        colWidths=[3 * inch, 2 * inch],
    )
    rates_table.setStyle(_TABLE_STYLE)
    elements.append(rates_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def build_all_campaigns_report_pdf(campaign_rows, summary):
    """
    campaign_rows: list of dicts, one per campaign — {name, status, sent_at,
    sent, delivered, opened, clicked, bounced, unsubscribed}. Same
    numbers-only principle: no per-recipient data anywhere in this report.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    elements = [
        Paragraph("Campaign Performance Report", _STYLES["Title"]),
        Spacer(1, 4),
        Paragraph(
            f"Totals across all campaigns — Sent: {summary['emails_sent']}, "
            f"Delivered: {summary['delivered']}, Opened: {summary['opened']}, "
            f"Clicked: {summary['clicked']}, Bounced: {summary['bounced']}, "
            f"Unsubscribed: {summary['unsubscribed']}",
            _STYLES["Normal"],
        ),
        Spacer(1, 18),
    ]

    header = ["Campaign", "Status", "Sent", "Delivered", "Opened", "Clicked", "Bounced", "Unsub'd"]
    data = [header]
    for row in campaign_rows:
        data.append(
            [
                Paragraph(row["name"], _STYLES["Normal"]),
                row["status"],
                row["sent"],
                row["delivered"],
                row["opened"],
                row["clicked"],
                row["bounced"],
                row["unsubscribed"],
            ]
        )

    table = Table(data, colWidths=[1.8 * inch, 0.8 * inch, 0.55 * inch, 0.7 * inch, 0.6 * inch, 0.6 * inch, 0.6 * inch, 0.6 * inch], repeatRows=1)
    table.setStyle(_TABLE_STYLE)
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
