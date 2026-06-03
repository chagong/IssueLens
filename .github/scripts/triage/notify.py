#!/usr/bin/env python3
"""Send triage notifications deterministically (no AI).

Reads a SLA-evaluated triage-results.json and:
  1. Sends one personal Teams notification per assignee with SLA violations
     (POST to PERSONAL_NOTIFICATION_URL), mapping github logins -> emails via
     the IDS environment variable.
  2. Sends a summary email of the whole triage run (POST to MAILING_URL) to
     REPORT_RECIPIENTS.

Because this runs as its own step with zero token budget, the summary email is
guaranteed to be sent regardless of how the AI labeling stage behaves.

Environment variables:
  PERSONAL_NOTIFICATION_URL  Logic App endpoint for personal Teams messages.
  MAILING_URL                Logic App endpoint for emails.
  REPORT_RECIPIENTS          Comma/semicolon-separated email recipients.
  IDS                        JSON array of {"github-id": ..., "email": ...}.

Usage:
    python notify.py --input triage-results.json \
        --workflow-url https://github.com/o/r/actions/runs/123 \
        --title "Daily Issue Triage Report"
"""

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
def post_json(url: str, payload: dict) -> int:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"  POST failed: {exc}", file=sys.stderr)
        return 0


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
def load_id_map() -> dict[str, str]:
    raw = os.environ.get("IDS", "").strip()
    if not raw:
        return {}
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        print("IDS env var is not valid JSON; skipping email mapping.", file=sys.stderr)
        return {}
    return {e["github-id"]: e["email"] for e in entries if e.get("github-id") and e.get("email")}


def recipients_list() -> list[str]:
    raw = os.environ.get("REPORT_RECIPIENTS", "")
    return [r.strip() for r in raw.replace(";", ",").split(",") if r.strip()]


# --------------------------------------------------------------------------- #
# Personal notifications
# --------------------------------------------------------------------------- #
def send_personal_notifications(violations: list[dict], workflow_url: str) -> int:
    url = os.environ.get("PERSONAL_NOTIFICATION_URL", "").strip()
    id_map = load_id_map()
    if not url:
        print("PERSONAL_NOTIFICATION_URL not set; skipping personal notifications.")
        return 0
    if not id_map:
        print("No IDS mapping available; skipping personal notifications.")
        return 0

    # Group violating issues by assignee login.
    by_login: dict[str, list[dict]] = {}
    for issue in violations:
        for login in issue.get("assignees", []):
            by_login.setdefault(login, []).append(issue)

    sent = 0
    for login, issues in sorted(by_login.items()):
        email = id_map.get(login)
        if not email:
            print(f"  No email for @{login}; skipping.")
            continue
        rows = "\n".join(
            f"| [#{i['issue_number']}]({i['url']}) | {i['title']} | {i['days_open']} | {i['sla_details']} |"
            for i in sorted(issues, key=lambda x: x["days_open"], reverse=True)
        )
        message = (
            f"## SLA Violations Assigned to You\n\n"
            f"You have **{len(issues)}** issue(s) that have exceeded the SLA grace period "
            f"and need attention.\n\n"
            f"| Issue | Title | Days Open | Reason |\n"
            f"|-------|-------|-----------|--------|\n"
            f"{rows}\n"
        )
        payload = {
            "title": f"SLA Violations Needing Attention - {date.today():%B %d, %Y}",
            "message": message,
            "workflowRunUrl": workflow_url,
            "recipient": email,
        }
        status = post_json(url, payload)
        ok = 200 <= status < 300
        print(f"  Personal notification to {email} ({len(issues)} issues): HTTP {status} {'OK' if ok else 'FAILED'}")
        sent += 1 if ok else 0
    return sent


# --------------------------------------------------------------------------- #
# Summary email
# --------------------------------------------------------------------------- #
def build_summary_html(issues: list[dict], counts: dict, workflow_url: str) -> str:
    violations = [i for i in issues if i["sla_status"] == "VIOLATION"]

    # Top assignees by violation count.
    by_login: dict[str, int] = {}
    for issue in violations:
        for login in issue.get("assignees", []):
            by_login[login] = by_login.get(login, 0) + 1
    top_assignees = sorted(by_login.items(), key=lambda x: x[1], reverse=True)[:10]

    # Top 20 oldest violations.
    oldest = sorted(violations, key=lambda x: x["days_open"], reverse=True)[:20]

    def esc(text: str) -> str:
        return html.escape(str(text))

    counts_html = (
        '<table style="border-collapse: collapse; width: 100%;">'
        '<tr style="background:#f6f8fa;">'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Metric</th>'
        '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Count</th></tr>'
        f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">Total issues triaged</td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{counts["total"]}</td></tr>'
        f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">✅ SLA Good</td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{counts["GOOD"]}</td></tr>'
        f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">⚠️ SLA Warning</td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{counts["WARNING"]}</td></tr>'
        f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">❌ SLA Violation</td>'
        f'<td style="border:1px solid #e1e4e8;padding:8px;">{counts["VIOLATION"]}</td></tr>'
        "</table>"
    )

    if top_assignees:
        rows = "".join(
            f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">@{esc(login)}</td>'
            f'<td style="border:1px solid #e1e4e8;padding:8px;">{count}</td></tr>'
            for login, count in top_assignees
        )
        assignees_html = (
            '<table style="border-collapse: collapse; width: 100%;">'
            '<tr style="background:#f6f8fa;">'
            '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Assignee</th>'
            '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Violations</th></tr>'
            f"{rows}</table>"
        )
    else:
        assignees_html = "<p>No SLA violations with assignees.</p>"

    if oldest:
        rows = "".join(
            f'<tr><td style="border:1px solid #e1e4e8;padding:8px;">'
            f'<a href="{esc(i["url"])}" style="color:#0366d6;">#{i["issue_number"]}</a></td>'
            f'<td style="border:1px solid #e1e4e8;padding:8px;">{esc(i["title"])}</td>'
            f'<td style="border:1px solid #e1e4e8;padding:8px;">{i["days_open"]}</td>'
            f'<td style="border:1px solid #e1e4e8;padding:8px;">{esc(", ".join(i.get("assignees", [])) or "—")}</td></tr>'
            for i in oldest
        )
        oldest_html = (
            '<table style="border-collapse: collapse; width: 100%;">'
            '<tr style="background:#f6f8fa;">'
            '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Issue</th>'
            '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Title</th>'
            '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Days Open</th>'
            '<th style="border:1px solid #e1e4e8;padding:8px;text-align:left;">Assignees</th></tr>'
            f"{rows}</table>"
        )
    else:
        oldest_html = "<p>No SLA violations.</p>"

    return (
        '<h2 style="color:#24292e;">Triage Summary</h2>'
        f"{counts_html}"
        '<h2 style="color:#24292e;margin-top:24px;">Top Assignees with SLA Violations</h2>'
        f"{assignees_html}"
        '<h2 style="color:#24292e;margin-top:24px;">20 Oldest SLA Violations</h2>'
        f"{oldest_html}"
    )


def send_summary_email(
    issues: list[dict],
    counts: dict,
    workflow_url: str,
    title: str,
    content_override: str | None = None,
) -> bool:
    url = os.environ.get("MAILING_URL", "").strip()
    recipients = recipients_list()
    if not url:
        print("MAILING_URL not set; skipping summary email.")
        return False
    if not recipients:
        print("REPORT_RECIPIENTS not set; skipping summary email.")
        return False

    time_frame = f"{date.today():%B %d, %Y}"
    content = content_override if content_override else build_summary_html(issues, counts, workflow_url)
    body = (
        '<html><body style="font-family: Arial, sans-serif; line-height: 1.6; '
        'color: #333; max-width: 800px; margin: 0 auto; padding: 20px;">'
        '<div style="background: #f6f8fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">'
        f'<h1 style="color: #0366d6; margin: 0;">{html.escape(title)}</h1>'
        f'<p style="color: #586069; margin: 5px 0 0 0;">{time_frame}</p></div>'
        f"{content}"
        '<hr style="border: none; border-top: 1px solid #e1e4e8; margin: 20px 0;">'
        '<p style="color: #586069; font-size: 12px;">Generated by '
        f'<a href="{html.escape(workflow_url)}" style="color: #0366d6;">GitHub Actions workflow</a>'
        "</p></body></html>"
    )
    payload = {
        "title": title,
        "timeFrame": time_frame,
        "body": body,
        "workflowRunUrl": workflow_url,
        "recipients": recipients,
    }
    status = post_json(url, payload)
    ok = 200 <= status < 300
    print(f"Summary email to {len(recipients)} recipient(s): HTTP {status} {'OK' if ok else 'FAILED'}")
    return ok


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--workflow-url", default="")
    parser.add_argument("--title", default="Daily Issue Triage Report")
    parser.add_argument(
        "--mode",
        choices=["all", "personal", "email"],
        default="all",
        help="personal = only Teams notifications; email = only summary email.",
    )
    parser.add_argument(
        "--content-file",
        default="",
        help="Path to a pre-rendered HTML fragment to use as the email body "
        "(e.g. the chart report). Falls back to the built-in summary tables.",
    )
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        issues = json.load(fh)

    counts = {
        "total": len(issues),
        "GOOD": sum(1 for i in issues if i.get("sla_status") == "GOOD"),
        "WARNING": sum(1 for i in issues if i.get("sla_status") == "WARNING"),
        "VIOLATION": sum(1 for i in issues if i.get("sla_status") == "VIOLATION"),
    }
    print(
        f"Loaded {counts['total']} issues "
        f"({counts['GOOD']} GOOD, {counts['WARNING']} WARNING, {counts['VIOLATION']} VIOLATION)"
    )

    violations = [i for i in issues if i.get("sla_status") == "VIOLATION"]

    if args.mode in ("all", "personal"):
        send_personal_notifications(violations, args.workflow_url)

    if args.mode in ("all", "email"):
        content_override = None
        if args.content_file and os.path.exists(args.content_file):
            with open(args.content_file, encoding="utf-8") as fh:
                content_override = fh.read()
        email_ok = send_summary_email(
            issues, counts, args.workflow_url, args.title, content_override
        )
        # Non-zero exit if the email (the critical deliverable) failed to send.
        return 0 if email_ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
