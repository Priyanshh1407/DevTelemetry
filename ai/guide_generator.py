import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

model_id = "gemini-2.5-flash"

# Bound how long one request can wait on the LLM. The SDK retries 408/429/5xx with
# exponential backoff; 2 attempts keeps the worst case near 2 x timeout.
LLM_TIMEOUT_MS = int(os.getenv("LLM_TIMEOUT_MS", "15000"))
LLM_MAX_ATTEMPTS = 2

# Created on first use, not at import: a missing key must only disable AI features,
# not stop the whole API from starting.
_client = None


class AIUnavailableError(RuntimeError):
    """Raised when the AI provider cannot be used (e.g. no API key configured)."""


def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise AIUnavailableError("GEMINI_API_KEY is not set")
        _client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=LLM_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=LLM_MAX_ATTEMPTS, initial_delay=1.0, max_delay=5.0),
            ),
        )
    return _client

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
        response_text = get_client().models.generate_content(
            model=model_id,
            contents=prompt
        ).text
        
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
        return get_client().models.generate_content(
            model=model_id,
            contents=prompt
        ).text.replace('**', '')
    except Exception as e:
        return f"Error generating team report: System Offline." 