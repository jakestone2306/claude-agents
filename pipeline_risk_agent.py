import os
import json
from datetime import datetime, timezone
from anthropic import Anthropic

# ── Config ──────────────────────────────────────────────────────────────────
HUBSPOT_TOKEN   = os.environ["HUBSPOT_TOKEN"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
MANAGER_SLACK_ID = os.environ.get("MANAGER_SLACK_ID", "U08357HEYJF")  # Jake Stone

# HubSpot owner_id → Slack user_id
OWNER_SLACK_MAP = {
    "85012029":  "U09RZCGQQJJ",  # Octavio Pala
    "88178787":  "U0AE5DA12N9",  # Brandon Perez
    "300195503": "U07R34DT45S",  # Jacob Bolton
    "299068163": "U02F8F5B8RM",  # Jacob Simon
    "84032188":  "U09KUM1CP5K",  # Kylene Warne
    "170827178": "U08357HEYJF",  # Jake Stone
}

OWNER_NAME_MAP = {
    "85012029":  "Octavio Pala",
    "88178787":  "Brandon Perez",
    "300195503": "Jacob Bolton",
    "299068163": "Jacob Simon",
    "84032188":  "Kylene Warne",
    "170827178": "Jake Stone",
}

EXCLUDED_STAGES = {
    "closedwon", "closedlost", "941713498",   # Churned (Sales Pipeline)
    "998944549",                               # Demo - No Show
    "1104889877",                              # Churned (Growth)
    "982154351", "1012659618",                 # Closed Lost variants
}

# ── HubSpot helpers ──────────────────────────────────────────────────────────
import urllib.request, urllib.parse

def hs_get(path, params=None):
    url = f"https://api.hubapi.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {HUBSPOT_TOKEN}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def hs_post(path, body):
    url = f"https://api.hubapi.com{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {HUBSPOT_TOKEN}",
        "Content-Type": "application/json"
    }, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def fetch_active_deals():
    """Fetch all active deals excluding closed/churned/no-show stages."""
    body = {
        "filterGroups": [
            {"filters": [
                {"propertyName": "dealstage", "operator": "NOT_IN",
                 "values": list(EXCLUDED_STAGES)}
            ]}
        ],
        "properties": [
            "dealname", "dealstage", "amount", "closedate",
            "hubspot_owner_id", "hs_last_activity_date",
            "pipeline", "description", "hs_deal_stage_probability",
            "hs_lastmodifieddate"
        ],
        "limit": 200,
        "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}]
    }
    result = hs_post("/crm/v3/objects/deals/search", body)
    return result.get("results", [])

def create_hs_task(deal_id, owner_id, subject, body_note, due_ts_ms):
    """Create a HubSpot task associated with a deal."""
    task = hs_post("/crm/v3/objects/tasks", {
        "properties": {
            "hs_task_subject": subject,
            "hs_task_body": body_note,
            "hubspot_owner_id": owner_id,
            "hs_task_status": "NOT_STARTED",
            "hs_timestamp": str(due_ts_ms),
            "hs_task_priority": "HIGH",
            "hs_task_type": "TODO"
        }
    })
    task_id = task["id"]
    # Associate task with deal
    hs_post(f"/crm/v4/objects/tasks/{task_id}/associations/deals/{deal_id}/batch/create",
        [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 216}])
    return task_id

# ── Slack helpers ─────────────────────────────────────────────────────────────
def slack_post(channel, text, blocks=None):
    url = "https://slack.com/api/chat.postMessage"
    body = {"channel": channel, "text": text}
    if blocks:
        body["blocks"] = blocks
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# ── Claude analysis ───────────────────────────────────────────────────────────
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

STAGE_LABELS = {
    "appointmentscheduled": "Demo Scheduled",
    "1083966814": "Post Demo - Pending Internal Alignment",
    "1083966816": "Follow Up Meeting Scheduled",
    "1083966815": "Pricing Estimate Delivered",
    "1083966817": "Pending IT/Legal Review",
    "1083966818": "Pending Customer Reference",
    "contractsent": "Onboarding Scheduled",
    "1009943555": "On Hold - Long Term",
    "1072305424": "OB Held",
    "1045587374": "Further OB Work Needed",
    "1104816808": "Pilot Period",
    "1243051167": "Contracted Pilot Period",
    "1243051168": "Expansion Opportunity",
    "1045587373": "At Risk [ACTIONABLE]",
    "1243051169": "At Risk [NON-ACTIONABLE]",
    "1243051170": "Retention Convo",
    "1243051171": "Winback Opportunity",
    "980617890": "Initial Discovery",
    "1012659612": "Initial Discovery",
    "1012659613": "Building Partnership Case",
    "1012659614": "Partnership Proposal Sent",
    "1012659617": "Partnership Agreement In Place",
}

def analyze_deals_with_claude(deals):
    today = datetime.now(timezone.utc)
    deal_summaries = []
    for d in deals:
        p = d["properties"]
        last_activity = p.get("hs_last_activity_date") or p.get("hs_lastmodifieddate", "")
        days_stale = None
        if last_activity:
            try:
                dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                days_stale = (today - dt).days
            except:
                pass
        close_date = p.get("closedate", "")
        days_to_close = None
        if close_date:
            try:
                dt = datetime.fromisoformat(close_date.replace("Z", "+00:00"))
                days_to_close = (dt - today).days
            except:
                pass

        stage_label = STAGE_LABELS.get(p.get("dealstage", ""), p.get("dealstage", "Unknown"))
        owner_name = OWNER_NAME_MAP.get(p.get("hubspot_owner_id", ""), "Unknown")

        deal_summaries.append({
            "id": d["id"],
            "name": p.get("dealname") or "(Unnamed)",
            "stage": stage_label,
            "amount": p.get("amount"),
            "owner": owner_name,
            "owner_id": p.get("hubspot_owner_id"),
            "days_stale": days_stale,
            "days_to_close": days_to_close,
            "probability": float(p.get("hs_deal_stage_probability") or 0),
            "description": p.get("description", "")
        })

    prompt = f"""You are a sales intelligence agent for Adapt Insurance, an insurance agency automation platform.

Today is {today.strftime('%B %d, %Y')}.

Here are the active deals in the pipeline (excluding Closed Won, Closed Lost, No Show, Churned):

{json.dumps(deal_summaries, indent=2)}

Your job:
1. Identify which deals are AT RISK (stale >7 days with no activity, overdue close dates, low probability stuck in early stages, or contextual red flags).
2. For EACH at-risk deal, recommend ONE specific next action the owner should take to accelerate it.
3. Produce a manager summary and individual rep action items.

Respond ONLY with valid JSON in this exact format:
{{
  "at_risk_deals": [
    {{
      "deal_id": "...",
      "deal_name": "...",
      "owner": "...",
      "owner_id": "...",
      "amount": "...",
      "stage": "...",
      "risk_reason": "One sentence why this deal is at risk",
      "recommended_action": "One specific, concrete action the rep should take today",
      "task_subject": "Short task title (max 60 chars)",
      "urgency": "HIGH|MEDIUM|LOW"
    }}
  ],
  "manager_summary": "3-5 sentence overview of pipeline health, biggest risks, and revenue at stake for the manager"
}}
"""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ── Main agent ────────────────────────────────────────────────────────────────
def run():
    print("🔍 Fetching active deals from HubSpot...")
    deals = fetch_active_deals()
    print(f"   Found {len(deals)} active deals")

    print("🤖 Analyzing deals with Claude...")
    analysis = analyze_deals_with_claude(deals)
    at_risk = analysis["at_risk_deals"]
    summary = analysis["manager_summary"]
    print(f"   Identified {len(at_risk)} at-risk deals")

    # ── 1. Slack the manager with full summary ────────────────────────────────
    today_str = datetime.now().strftime("%B %d, %Y")
    urgency_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}

    manager_blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 Pipeline Risk Report — {today_str}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{len(at_risk)} deals flagged at risk:*"}},
    ]

    for deal in at_risk:
        emoji = urgency_emoji.get(deal["urgency"], "🟡")
        amount_str = f"${float(deal['amount']):,.0f}" if deal.get("amount") else "No amount"
        manager_blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": (f"{emoji} *{deal['deal_name']}* — {amount_str}\n"
                              f"Owner: {deal['owner']} | Stage: {deal['stage']}\n"
                              f"⚠️ {deal['risk_reason']}\n"
                              f"✅ *Action:* {deal['recommended_action']}")}
        })
        manager_blocks.append({"type": "divider"})

    slack_post(MANAGER_SLACK_ID, f"Pipeline Risk Report — {len(at_risk)} deals at risk", manager_blocks)
    print(f"✅ Manager summary sent to Slack")

    # ── 2. DM each rep their action items + create HubSpot tasks ─────────────
    # Group by owner
    by_owner = {}
    for deal in at_risk:
        oid = deal["owner_id"]
        by_owner.setdefault(oid, []).append(deal)

    # Due date = tomorrow noon UTC in ms
    tomorrow_ms = int((datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0).timestamp() + 86400) * 1000)

    for owner_id, owner_deals in by_owner.items():
        slack_id = OWNER_SLACK_MAP.get(owner_id)
        owner_name = OWNER_NAME_MAP.get(owner_id, "Rep")

        # Send Slack DM
        if slack_id:
            rep_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"👋 Your Deal Actions — {today_str}"}},
                {"type": "section", "text": {"type": "mrkdwn",
                    "text": f"Hey {owner_name.split()[0]}! Here are your deals that need attention today:"}},
                {"type": "divider"},
            ]
            for deal in owner_deals:
                emoji = urgency_emoji.get(deal["urgency"], "🟡")
                amount_str = f"${float(deal['amount']):,.0f}" if deal.get("amount") else "No amount set"
                hs_url = f"https://app.hubspot.com/contacts/23695809/record/0-3/{deal['deal_id']}"
                rep_blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn",
                             "text": (f"{emoji} *<{hs_url}|{deal['deal_name']}>* — {amount_str}\n"
                                      f"Stage: {deal['stage']}\n"
                                      f"⚠️ {deal['risk_reason']}\n"
                                      f"✅ *Your action:* {deal['recommended_action']}")}
                })
                rep_blocks.append({"type": "divider"})

            slack_post(slack_id, f"You have {len(owner_deals)} deals needing attention", rep_blocks)
            print(f"   ✅ Slack DM sent to {owner_name}")

        # Create HubSpot tasks
        for deal in owner_deals:
            try:
                task_id = create_hs_task(
                    deal_id=deal["deal_id"],
                    owner_id=owner_id,
                    subject=deal["task_subject"],
                    body_note=f"{deal['risk_reason']}\n\nRecommended action: {deal['recommended_action']}",
                    due_ts_ms=tomorrow_ms
                )
                print(f"   ✅ HubSpot task created for {deal['deal_name']} (task {task_id})")
            except Exception as e:
                print(f"   ⚠️  Task creation failed for {deal['deal_name']}: {e}")

    print(f"\n🎉 Done! Processed {len(at_risk)} at-risk deals across {len(by_owner)} reps.")

if __name__ == "__main__":
    run()
