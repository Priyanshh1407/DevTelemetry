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
