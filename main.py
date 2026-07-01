import json
import os
import sys

# Ensure stdout can print emojis on Windows
sys.stdout.reconfigure(encoding='utf-8')
from core.scorer import calculate_efficiency_score
from ai.guide_generator import generate_efficiency_guide, generate_team_report
from data.seed import generate_historical_data

def main():
    file_path = "engineers_data.json"

    if not os.path.exists(file_path):
        print("Generating mock telemetry data...")
        generate_historical_data()

    with open(file_path, "r") as f:
        engineers = json.load(f)
    
    # Score engineers
    for eng in engineers:
        eng["efficiency_score"] = calculate_efficiency_score(eng)
    
    # Sort by efficiency (highest score first)
    engineers.sort(key=lambda x: x["efficiency_score"], reverse=True)
    
    # Calculate Team Summary for the general report
    avg_score = sum(e["efficiency_score"] for e in engineers) / len(engineers)
    total_spend = sum(e["estimated_cost_usd"] for e in engineers)
    team_summary = {
        "team_size": len(engineers),
        "average_efficiency_score": round(avg_score, 2),
        "total_daily_spend_usd": round(total_spend, 2)
    }

    # Print Leaderboard
    print("\n" + "="*65)
    print(f"🏆 DEVTELEMETRY: EFFICIENCY LEADERBOARD")
    print("="*65)
    print(f"{'Rank':<5} | {'Name':<22} | {'Score':<6} | {'Spend ($)':<10}")
    print("-" * 65)
    
    for i, eng in enumerate(engineers, 1):
        print(f"{i:<5} | {eng['name']:<22} | {eng['efficiency_score']:<6.2f} | ${eng['estimated_cost_usd']:<10.2f}")
    
    # Generate and Print Team General Report
    print("\n" + "="*65)
    print("📢 TEAM-WIDE OPTIMIZATION REPORT")
    print("="*65)
    print(generate_team_report(team_summary))

    # Generate Individual Guides for Bottom 5
    print("\n" + "="*65)
    print("🚨 INDIVIDUAL COACHING GUIDES (BOTTOM 5)")
    print("="*65)
    
    # Slice the last 5 engineers from the sorted list
    bottom_5 = engineers[-5:]
    
    # We enumerate to easily identify the absolute worst (index 4 in a list of 5)
    for index, eng in enumerate(bottom_5):
        # The engineer's actual rank is their position in the total list (Total - 5 + current index + 1)
        actual_rank = len(engineers) - 5 + index + 1
        
        # Apply strict severity only to the absolute worst performer
        severity = "critical" if index >=3 else "moderate"
        
        print(f"\n--- Coaching for {eng['name']} (Rank: {actual_rank}, Score: {eng['efficiency_score']:.2f}) ---")
        guide = generate_efficiency_guide(eng, severity=severity)
        print(guide)

if __name__ == "__main__":
    main()