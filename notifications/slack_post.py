import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()


# Read at call time (not import) so tests and runtime config decide where messages go.
SLACK_TIMEOUT_SECONDS = 10  # never let a slow Slack hang the dispatch


def _webhook_url():
    return os.getenv("SLACK_WEBHOOK_URL")


def _dashboard_url():
    # Previously hardcoded to localhost, so the deployed Slack button pointed at the reader's own machine.
    return os.getenv("FRONTEND_URL", "http://localhost:5173")


def _build_slack_blocks(all_devs, average_score, total_cost):
    """
    Builds a Slack Block Kit message payload for the manager channel.
    Shows team snapshot, top performers, bottom performers, and a dashboard link.
    """

    total_devs = len(all_devs)

    # ── Top 5 performers ──
    top_lines = []
    for dev in all_devs[:5]:
        severity_emoji = {"low": ":large_green_circle:", "moderate": ":large_yellow_circle:", "critical": ":red_circle:"}.get(dev["severity"], ":white_circle:")
        top_lines.append(f"  `#{dev['rank']}`  *{dev['name']}* — {dev['efficiency_score']:.1f}  {severity_emoji}")

    # ── Bottom 2 (needs attention) ──
    bottom_lines = []
    for dev in all_devs[-2:]:
        waste = dev.get("primary_waste_pattern", "Low efficiency score")
        bottom_lines.append(f"  `#{dev['rank']}`  *{dev['name']}* — {dev['efficiency_score']:.1f}  :red_circle:  _{waste}_")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":bell: DevTelemetry — Weekly Efficiency Report",
                "emoji": True
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":bar_chart: *Team Snapshot*\n"
                    f"• *Team Average Score:*  `{average_score:.1f}` / 100\n"
                    f"• *Total Daily Spend:*  `${total_cost:.2f}`\n"
                    f"• *Engineers Tracked:*  `{total_devs}`"
                )
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":trophy: *Top Performers*\n" + "\n".join(top_lines)
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":rotating_light: *Needs Attention*\n" + "\n".join(bottom_lines)
            }
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": ":chart_with_upwards_trend: Open Dashboard",
                        "emoji": True
                    },
                    "url": _dashboard_url(),
                    "style": "primary"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Automated by DevTelemetry Intelligence Agent  •  Individual alerts dispatched via email_"
                }
            ]
        }
    ]

    return {"blocks": blocks}


def send_slack_summary(all_devs, average_score, total_cost):
    """
    Sends a formatted team summary to the configured Slack webhook channel.
    Gracefully skips if SLACK_WEBHOOK_URL is not set.
    Returns "sent", "failed" or "skipped".
    """

    webhook_url = _webhook_url()
    if not webhook_url:
        print("[SLACK] No SLACK_WEBHOOK_URL configured in .env — skipping Slack notification.")
        return "skipped"

    payload = _build_slack_blocks(all_devs, average_score, total_cost)
    json_data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=json_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=SLACK_TIMEOUT_SECONDS) as response:
            if response.status == 200:
                print("[SLACK] Team summary posted to Slack channel successfully!")
                return "sent"
            else:
                print(f"[SLACK] Unexpected response status: {response.status}")
                return "failed"

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"[SLACK] HTTP Error {e.code}: {error_body}")
        return "failed"

    except urllib.error.URLError as e:
        print(f"[SLACK] Connection error: {e.reason}")
        return "failed"

    except Exception as e:
        print(f"[SLACK] Unexpected error: {e}")
        return "failed"


if __name__ == "__main__":
    # Quick standalone test with mock data
    test_devs = [
        {"rank": 1, "name": "Test User 1", "efficiency_score": 85.0, "estimated_cost_usd": 5.50, "severity": "low"},
        {"rank": 2, "name": "Test User 2", "efficiency_score": 72.0, "estimated_cost_usd": 8.20, "severity": "low"},
        {"rank": 3, "name": "Test User 3", "efficiency_score": 65.0, "estimated_cost_usd": 10.10, "severity": "low"},
        {"rank": 4, "name": "Test User 4", "efficiency_score": 58.0, "estimated_cost_usd": 12.30, "severity": "low"},
        {"rank": 5, "name": "Test User 5", "efficiency_score": 55.0, "estimated_cost_usd": 14.00, "severity": "low"},
        {"rank": 6, "name": "Test User 6", "efficiency_score": 50.0, "estimated_cost_usd": 15.50, "severity": "moderate"},
        {"rank": 7, "name": "Test User 7", "efficiency_score": 48.0, "estimated_cost_usd": 16.80, "severity": "moderate"},
        {"rank": 8, "name": "Test User 8", "efficiency_score": 45.0, "estimated_cost_usd": 18.00, "severity": "moderate"},
        {"rank": 9, "name": "Test User 9", "efficiency_score": 38.0, "estimated_cost_usd": 22.40, "severity": "critical", "primary_waste_pattern": "High token waste"},
        {"rank": 10, "name": "Test User 10", "efficiency_score": 32.0, "estimated_cost_usd": 25.00, "severity": "critical", "primary_waste_pattern": "Over-reliance on Opus"},
    ]

    result = send_slack_summary(test_devs, average_score=54.8, total_cost=147.80)
    if result == "sent":
        print("\nTest passed — check your Slack channel!")
    else:
        print("\nTest failed — check the error messages above.")
