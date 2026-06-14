import random
from faker import Faker
from datetime import datetime, timedelta
import os
import sys

# Ensure Python can find our core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import get_db_connection, init_db
from core.scorer import calculate_efficiency_score

fake = Faker()

def generate_historical_data(days_back=30, num_engineers=10):
    print("Ensuring database tables exist...")
    init_db()
    print(f"Generating {days_back} days of historical data for {num_engineers} engineers...")
    
    # 1. Generate static engineers with synthesized emails
    engineers = []
    for _ in range(num_engineers):
        name = fake.name()
        # Creates a realistic email like "john.smith@company.com"
        email = f"{name.lower().replace(' ', '.')}@company.com" 
        engineers.append({
            "user_id": fake.uuid4(), 
            "name": name, 
            "email": email
        })
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Insert engineers into DB (Now includes the email column)
        for eng in engineers:
            cursor.execute(
                "INSERT OR IGNORE INTO engineers (user_id, name, email) VALUES (?, ?, ?)", 
                (eng["user_id"], eng["name"], eng["email"])
            )
            
        # 2. Generate 30 days of metrics for each engineer
        today = datetime.now()
        
        for day_offset in range(days_back):
            current_date = (today - timedelta(days=days_back - day_offset - 1)).strftime("%Y-%m-%d")
            
            for eng in engineers:
                input_tokens = random.randint(50000, 400000)
                cache_read_tokens = random.randint(0, int(input_tokens * 0.9))
                
                # Model mix generation
                opus_raw = random.uniform(0.0, 0.4)
                sonnet_raw = random.uniform(0.3, 0.8)
                haiku_raw = random.uniform(0.1, 0.5)
                
                total = opus_raw + sonnet_raw + haiku_raw
                opus_pct = round(opus_raw / total, 2)
                sonnet_pct = round(sonnet_raw / total, 2)
                haiku_pct = round(1.0 - opus_pct - sonnet_pct, 2)
                
                # Build the data dictionary (used for scoring)
                metrics = {
                    "input_tokens": input_tokens,
                    "output_tokens": random.randint(10000, 80000),
                    "cache_read_tokens": cache_read_tokens,
                    "cache_write_tokens": random.randint(5000, 50000),
                    "model_mix": {
                        "opus_pct": opus_pct,
                        "sonnet_pct": sonnet_pct,
                        "haiku_pct": haiku_pct
                    },
                    "session_count": random.randint(1, 8),
                    "compact_uses": random.randint(0, 5),
                    "git_commits": random.randint(0, 12),
                    "estimated_cost_usd": round(random.uniform(5.0, 30.0), 2)
                }
                
                # 3. Calculate the score BEFORE saving to DB
                efficiency_score = calculate_efficiency_score(metrics)
                
                # 4. Insert the daily record into the DB
                cursor.execute("""
                    INSERT OR IGNORE INTO usage_metrics 
                    (user_id, date, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, 
                    opus_pct, sonnet_pct, haiku_pct, session_count, compact_uses, git_commits, 
                    estimated_cost_usd, efficiency_score) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    eng["user_id"], current_date, metrics["input_tokens"], metrics["output_tokens"], 
                    metrics["cache_read_tokens"], metrics["cache_write_tokens"], opus_pct, sonnet_pct, haiku_pct, 
                    metrics["session_count"], metrics["compact_uses"], metrics["git_commits"], 
                    metrics["estimated_cost_usd"], efficiency_score
                ))
        
        conn.commit()
    print("Historical data successfully injected into the database!")

if __name__ == "__main__":
    generate_historical_data()