import json
import random
from faker import Faker
from datetime import date

fake = Faker()

def generate_mock_data(num_engineers=10):
    data = []
    for _ in range(num_engineers):
        input_tokens = random.randint(50000, 400000)
        cache_read_tokens = random.randint(0, int(input_tokens * 0.9))
        
        # 1. Generate raw weights based on realistic usage
        opus_raw = random.uniform(0.0, 0.4)    # Opus should generally be the lowest
        sonnet_raw = random.uniform(0.3, 0.8)  # Sonnet is the default/highest
        haiku_raw = random.uniform(0.1, 0.5)   # Haiku usage varies
        
        # 2. Normalize using your sum-and-divide logic
        total = opus_raw + sonnet_raw + haiku_raw
        
        opus_pct = round(opus_raw / total, 2)
        sonnet_pct = round(sonnet_raw / total, 2)
        # Force the final value to balance exactly to 1.0 to prevent 0.99/1.01 rounding weirdness
        haiku_pct = round(1.0 - opus_pct - sonnet_pct, 2)
        
        engineer = {
            "user_id": fake.uuid4(),
            "name": fake.name(),
            "date": str(date.today()),
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
        data.append(engineer)
    
    file_path = "engineers_data.json"
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)
    
    return data

if __name__ == "__main__":
    generate_mock_data()
    print("Successfully generated engineers_data.json")