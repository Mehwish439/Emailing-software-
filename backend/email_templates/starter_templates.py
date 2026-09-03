"""
A small library of starter email templates. Used by:
  - seed_data (creates real EmailTemplate rows from these for the demo user)
  - GET /api/templates/starters/ (frontend's "start from a template" gallery
    when creating a new template — see TemplateEditorPage.jsx)

Kept as one Python source of truth rather than duplicating the same HTML in
both the backend seed command and frontend JS.

Every starter includes the {{unsubscribe_url}} merge tag in its footer —
see brevo/services.py, which fills it in with a real per-recipient link at
send time. Templates built from these starters keep that footer unless the
user deletes it, which nudges toward better deliverability by default (see
the "Insert unsubscribe link" warning in the template editor for templates
that don't have one).
"""

_UNSUBSCRIBE_FOOTER = """<p style="font-size:12px;color:#94a3b8;text-align:center;margin-top:32px;">
  Don't want these emails? <a href="{{unsubscribe_url}}" style="color:#94a3b8;text-decoration:underline;">Unsubscribe</a>
</p>"""

STARTER_TEMPLATES = [
    {
        "key": "blank",
        "name": "Blank",
        "description": "A minimal starting point with just a heading and a call-to-action link.",
        "subject": "Hello from us!",
        "html_content": f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
  <h1 style="color: #2b47dd;">Hello {{{{first_name}}}}!</h1>
  <p>Write your email content here.</p>
  <p><a href="#" style="color: #2b47dd;">Call to action</a></p>
{_UNSUBSCRIBE_FOOTER}
</div>""",
    },
    {
        "key": "newsletter",
        "name": "Newsletter",
        "description": "A multi-section layout for a regular digest or roundup email.",
        "subject": "Your monthly update",
        "html_content": f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b;">
  <div style="background: #2b47dd; padding: 24px; text-align: center; border-radius: 8px 8px 0 0;">
    <h1 style="color: #ffffff; margin: 0; font-size: 22px;">This Month's Update</h1>
  </div>
  <div style="padding: 24px; border: 1px solid #e2e8f0; border-top: none;">
    <p>Hi {{{{first_name}}}},</p>
    <p>Here's what's new this month.</p>

    <h2 style="font-size: 16px; color: #2b47dd; margin-top: 24px;">Headline one</h2>
    <p>A short paragraph about your first update or story.</p>

    <h2 style="font-size: 16px; color: #2b47dd; margin-top: 24px;">Headline two</h2>
    <p>A short paragraph about your second update or story.</p>

    <p style="margin-top: 24px;"><a href="#" style="color: #2b47dd; font-weight: bold;">Read more &rarr;</a></p>
  </div>
{_UNSUBSCRIBE_FOOTER}
</div>""",
    },
    {
        "key": "product-announcement",
        "name": "Product Announcement",
        "description": "Announce a new feature or product launch with a prominent call-to-action.",
        "subject": "Introducing something new",
        "html_content": f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b; text-align: center;">
  <h1 style="color: #2b47dd; font-size: 24px;">Introducing [Product Name]</h1>
  <p style="font-size: 16px;">Hi {{{{first_name}}}}, we've been working on something we think you'll love.</p>
  <p>A short description of what's new and why it matters to your recipient.</p>
  <a href="#" style="display: inline-block; margin-top: 16px; padding: 12px 28px; background: #2b47dd; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: bold;">
    Check it out
  </a>
{_UNSUBSCRIBE_FOOTER}
</div>""",
    },
    {
        "key": "promotional",
        "name": "Promotional / Sale",
        "description": "A bold, discount-focused layout for sales and limited-time offers.",
        "subject": "A special offer just for you",
        "html_content": f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b; text-align: center;">
  <div style="background: #fef3c7; padding: 32px 24px; border-radius: 8px;">
    <p style="text-transform: uppercase; letter-spacing: 1px; color: #b45309; font-weight: bold; margin: 0;">Limited time</p>
    <h1 style="color: #1e293b; font-size: 32px; margin: 8px 0;">20% Off Everything</h1>
    <p style="color: #475569;">Hi {{{{first_name}}}}, use the code below at checkout before it expires.</p>
    <p style="font-size: 20px; font-weight: bold; letter-spacing: 2px; background: #ffffff; display: inline-block; padding: 10px 20px; border-radius: 6px; margin: 16px 0;">
      SAVE20
    </p>
    <br />
    <a href="#" style="display: inline-block; padding: 12px 28px; background: #2b47dd; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: bold;">
      Shop Now
    </a>
  </div>
{_UNSUBSCRIBE_FOOTER}
</div>""",
    },
    {
        "key": "welcome",
        "name": "Welcome / Onboarding",
        "description": "Greet a new subscriber or customer and point them to their next step.",
        "subject": "Welcome aboard!",
        "html_content": f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b;">
  <h1 style="color: #2b47dd;">Welcome, {{{{first_name}}}}!</h1>
  <p>Thanks for joining us. Here's a quick rundown of what to do next:</p>
  <ol style="padding-left: 20px; line-height: 1.8;">
    <li>Complete your profile</li>
    <li>Explore your dashboard</li>
    <li>Reach out any time if you have questions</li>
  </ol>
  <a href="#" style="display: inline-block; margin-top: 16px; padding: 12px 28px; background: #2b47dd; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: bold;">
    Get Started
  </a>
{_UNSUBSCRIBE_FOOTER}
</div>""",
    },
    {
        "key": "event-invitation",
        "name": "Event Invitation",
        "description": "Invite recipients to an upcoming event, webinar, or launch.",
        "subject": "You're invited",
        "html_content": f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b; text-align: center;">
  <h1 style="color: #2b47dd;">You're Invited</h1>
  <p style="font-size: 16px;">Hi {{{{first_name}}}}, join us for [Event Name].</p>
  <table style="margin: 20px auto; text-align: left; font-size: 14px; color: #475569;">
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Date</td><td>[Date]</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Time</td><td>[Time]</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; font-weight: bold;">Where</td><td>[Location or link]</td></tr>
  </table>
  <a href="#" style="display: inline-block; padding: 12px 28px; background: #2b47dd; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: bold;">
    Reserve Your Spot
  </a>
{_UNSUBSCRIBE_FOOTER}
</div>""",
    },
    {
        "key": "re-engagement",
        "name": "Re-engagement / We Miss You",
        "description": "Win back subscribers who haven't engaged in a while.",
        "subject": "We miss you",
        "html_content": f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #1e293b; text-align: center;">
  <h1 style="color: #2b47dd;">We miss you, {{{{first_name}}}}</h1>
  <p>It's been a while since we've heard from you. Here's what you've missed, and something to bring you back.</p>
  <a href="#" style="display: inline-block; margin-top: 12px; padding: 12px 28px; background: #2b47dd; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: bold;">
    See What's New
  </a>
  <p style="margin-top: 24px; font-size: 13px; color: #94a3b8;">
    Not interested anymore? No hard feelings — you can unsubscribe below.
  </p>
{_UNSUBSCRIBE_FOOTER}
</div>""",
    },
]


def get_starter(key):
    return next((t for t in STARTER_TEMPLATES if t["key"] == key), None)
