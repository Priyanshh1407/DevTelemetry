import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Initialize model once to reuse
model = genai.GenerativeModel("gemini-2.5-flash")

def generate_efficiency_guide(engineer_data, severity="moderate"):
    """
    Generates a personalized guide. Tone and length adjust based on severity.
    """
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
    2. Format it as a simple numbered list without markdown bolding in the list numbers.
    3. Keep it concise and professional.
    """
    
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Error generating guide: {str(e)}"

def generate_team_report(team_summary):
    """
    Generates a broad, general optimization report for the entire engineering team.
    """
    prompt = f"""
    You are an AI usage analyst writing a daily memo for an engineering team using the 'Claude Code' AI agent.
    
    Here is the team's aggregate performance for the day:
    {json.dumps(team_summary, indent=2)}
    
    Write a brief, 2-paragraph general report for the team. 
    - Paragraph 1: State the overall health, celebrating the good metrics.
    - Paragraph 2: Provide 2 general best practices for the whole team to focus on tomorrow to optimize costs and efficiency.
    
    Keep the tone encouraging, professional, and collaborative.
    """
    
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Error generating team report: {str(e)}"