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
    Includes fallback data if the API rate limit is hit.
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
    2. Format it as a simple numbered list. DO NOT use markdown formatting like **bold** or bullet points. Just plain text.
    3. Keep it concise and professional.
    """
    
    try:
        response_text = model.generate_content(prompt).text
        
        tasks = []
        for line in response_text.split('\n'):
            line = line.strip()
            if line and line[0].isdigit() and '. ' in line[:4]:
                clean_text = line.split('. ', 1)[1].strip()
                
                # Strip out stray markdown asterisks that the AI ignores rules to include
                clean_text = clean_text.replace('**', '').replace('*', '')
                
                tasks.append({
                    "title": "Optimization Action", 
                    "desc": clean_text
                })
                
        if not tasks:
            tasks = [{"title": "AI Summary", "desc": response_text.replace('**', '')}]
            
        return tasks

    except Exception as e:
        error_str = str(e)
        
        # 1. Handle Rate Limits Gracefully
        if "429" in error_str or "quota" in error_str.lower():
            print("API Rate Limit Hit. Deploying fallback runbook...")
            return [
                {"title": "System Notice: API Rate Limit", "desc": "Personalized generation is paused due to Gemini API limits. Showing standard procedures."},
                {"title": "Audit Token Looping", "desc": "Check agent logs for repetitive, failing task loops."},
                {"title": "Enforce Model Tiering", "desc": "Shift non-essential background tasks to Haiku/Flash models."},
                {"title": "Consolidate Prompts", "desc": "Batch multiple instructions into a single context window."}
            ]
            
        # 2. Handle Total API Failure (e.g., No Internet)
        print(f"API Error: {error_str}")
        return [
            {"title": "AI Service Offline", "desc": "Unable to connect to the intelligence engine."},
            {"title": "Manual Intervention", "desc": "Please review the raw telemetry metrics directly."}
        ]


def generate_team_report(team_summary):
    # ... (Keep this exactly as you had it) ...
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
        return model.generate_content(prompt).text.replace('**', '')
    except Exception as e:
        return f"Error generating team report: System Offline." 