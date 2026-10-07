"""Prompt templates for the LLM features.

The exact text is pinned by tests/test_prompts.py (golden files): changing a prompt is a
deliberate, reviewed diff, never a side effect of a refactor.
"""
import json


def build_guide_prompt(engineer_data, severity):
    """Prompt for one engineer's coaching guide. "critical" gets a 5-point intervention; everyone
    else (including "low", i.e. top performers) currently gets the 3-point nudge."""
    if severity == "critical":
        tone_instructions = "You are doing a direct, serious intervention. Generate a highly detailed, 5-point actionable guide to drastically reduce their token waste."
    else:
        tone_instructions = "You are giving a gentle, constructive nudge to someone slightly below average. Generate a quick, friendly 3-point tip list to help them improve."

    prompt = f"""
    You are an AI usage analyst helping developers optimize their 'Claude Code' terminal agent usage. 
    Analyze the daily usage statistics below for a specific engineer.
    
    Developer Data:
    {json.dumps(engineer_data, indent=2)}
    
    {tone_instructions}
    
    Rules:
    1. Reference their actual data points in the advice (e.g., "Your cache ratio is X%").
    2. Format it as a simple numbered list. DO NOT use markdown formatting like **bold** or bullet points. Just plain text.
    3. Keep it concise and professional.
    """
    return prompt


def build_team_report_prompt(team_summary):
    """Prompt for the manager digest's two-paragraph team memo."""
    prompt = f"""
    You are an AI usage analyst writing a daily memo for an engineering team using the 'Claude Code' AI agent.
    
    Here is the team's aggregate performance for the day:
    {json.dumps(team_summary, indent=2)}
    
    Write a brief, 2-paragraph general report for the team. 
    - Paragraph 1: State the overall health, celebrating the good metrics.
    - Paragraph 2: Provide 2 general best practices for the whole team to focus on tomorrow to optimize costs and efficiency.
    
    Keep the tone encouraging, professional, and collaborative.
    """
    return prompt


# ── Prompt v2 (UPG-01): structured output from precomputed facts ────────────
# v1 (above) sends the raw database row and asks for a numbered plain-text list. It stays
# unchanged as the eval baseline. v2 gives the model named facts with exact values, asks for
# JSON matching ai.schemas.CoachingGuide, and forbids numbers that aren't in FACTS.
PROMPT_VERSION = "v2"

_TONES = {
    "critical": ("This engineer is in the team's bottom two this week. Be direct and specific.", 4),
    "moderate": ("Give a friendly, constructive nudge.", 3),
    "low": ("This engineer is among the team's top performers. Acknowledge what is working, then suggest "
            "how to keep or refine their habits.", 2),
}
_AREA_LABELS = {"cache": "prompt caching", "model_mix": "model choice", "discipline": "context management (/compact)"}


def build_guide_prompt_v2(facts, severity):
    tone, n_actions = _TONES.get(severity, _TONES["moderate"])
    weakest = facts["weakest_area"]
    points, lost = facts["points"], facts["points_lost"]
    return f"""You coach one software engineer on using Claude Code (an AI coding agent) cost-efficiently.

FACTS (the only numbers you may use):
- Efficiency score: {facts["efficiency_score"]} / 100
- Cache: {facts["cache_hit_pct"]}% of prompt tokens were served from cache ({points["cache"]} of 40 points)
- Model mix: Opus {facts["opus_pct"]}%, Sonnet {facts["sonnet_pct"]}%, Haiku {facts["haiku_pct"]}% ({points["model_mix"]} of 30 points)
- /compact: used in {facts["compact_rate_7d_pct"]}% of sessions over the last 7 days ({facts["compacts_7d"]} of {facts["sessions_7d"]} sessions; {points["discipline"]} of 30 points)
- Estimated cost today: ${facts["cost_usd"]:.2f}
- Weakest area: {weakest} ({_AREA_LABELS[weakest]}), {lost[weakest]} points below its maximum

TASK: {tone} Write {n_actions} actions.

RULES:
1. The first action must address the weakest area ({weakest}).
2. Every number you write must appear in FACTS exactly as shown. Do not invent statistics,
   savings estimates, percentages or time intervals.
3. "focus" names the area an action improves: cache, model_mix or discipline.
4. Plain sentences, no markdown.

Reply with JSON only, matching the provided schema."""


# ── Prompt v3 (UPG-06): v2 plus savings the code computed ───────────────────
# v2 forbids savings estimates because a model-estimated saving is invented by construction.
# v3 gives the model savings that core/whatif.py computed by re-pricing the engineer's real
# tokens, so a guide can say what a habit costs in money and still be fully grounded.
PROMPT_VERSION_V3 = "v3"


def _saving_line(label, target_pct, saving):
    if saving <= 0:
        return f"- {label}: already at or better than the team's top quartile ({target_pct}%); no saving to quote"
    return f"- {label} at the team's top quartile ({target_pct}%) would save ${saving:.2f} per 30 days"


def build_guide_prompt_v3(facts, severity):
    tone, n_actions = _TONES.get(severity, _TONES["moderate"])
    weakest = facts["weakest_area"]
    points, lost = facts["points"], facts["points_lost"]
    savings = facts.get("savings")
    savings_block = ""
    if savings:
        savings_block = (
            f"\nSAVINGS (computed by re-pricing this engineer's real tokens from the last "
            f"{savings['window_days']} days):\n"
            + _saving_line("Cache hit ratio", savings["cache_target_pct"], savings["saving_month_usd_cache"]) + "\n"
            + _saving_line("Opus share", savings["opus_target_pct"], savings["saving_month_usd_model"]) + "\n")
    return f"""You coach one software engineer on using Claude Code (an AI coding agent) cost-efficiently.

FACTS (the only numbers you may use):
- Efficiency score: {facts["efficiency_score"]} / 100
- Cache: {facts["cache_hit_pct"]}% of prompt tokens were served from cache ({points["cache"]} of 40 points)
- Model mix: Opus {facts["opus_pct"]}%, Sonnet {facts["sonnet_pct"]}%, Haiku {facts["haiku_pct"]}% ({points["model_mix"]} of 30 points)
- /compact: used in {facts["compact_rate_7d_pct"]}% of sessions over the last 7 days ({facts["compacts_7d"]} of {facts["sessions_7d"]} sessions; {points["discipline"]} of 30 points)
- Estimated cost today: ${facts["cost_usd"]:.2f}
- Weakest area: {weakest} ({_AREA_LABELS[weakest]}), {lost[weakest]} points below its maximum
{savings_block}
TASK: {tone} Write {n_actions} actions.

RULES:
1. The first action must address the weakest area ({weakest}).
2. Every number you write must appear in FACTS or SAVINGS exactly as shown. Do not invent statistics,
   percentages or time intervals, and do not estimate any saving yourself.
3. When an action is about cache or model_mix and SAVINGS gives a saving for it, quote that saving.
4. "focus" names the area an action improves: cache, model_mix or discipline.
5. Plain sentences, no markdown.

Reply with JSON only, matching the provided schema."""


def build_repair_prompt(original_prompt, error):
    return (f"{original_prompt}\n\nYour previous reply was not valid: {error}\n"
            "Reply again with JSON only that matches the schema.")
