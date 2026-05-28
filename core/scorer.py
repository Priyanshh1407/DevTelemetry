import json
import random
from faker import Faker
from datetime import date
import os

fake = Faker()

def calculate_efficiency_score(engineer_data):
    """
    Calculates efficiency score (0-100) based on:
    - Cache hit ratio (40 pts)
    - Model mix score (30 pts)
    - Session discipline (30 pts)
    """
    
    # 1. Cache hit ratio (40% weight)
    input_tokens = engineer_data["input_tokens"]
    cache_read = engineer_data["cache_read_tokens"]
    cache_ratio = cache_read / input_tokens if input_tokens > 0 else 0
    cache_score = min(cache_ratio, 1.0) * 40
    
    # 2. Model mix score (30% weight)
    # Target: Haiku = 1.0 weight, Sonnet = 0.6 weight, Opus = 0.1 weight
    mix = engineer_data["model_mix"]
    mix_ratio = (mix.get("haiku_pct", 0) * 1.0) + \
                (mix.get("sonnet_pct", 0) * 0.6) + \
                (mix.get("opus_pct", 0) * 0.1)
    model_score = mix_ratio * 30
    
    # 3. Session discipline score (30% weight)
    # Calculated as the ratio of /compact uses to session count
    sessions = engineer_data["session_count"]
    compacts = engineer_data["compact_uses"]
    
    compact_ratio = compacts / sessions if sessions > 0 else 0
    discipline_score = min(compact_ratio, 1.0) * 30
    
    total_score = cache_score + model_score + discipline_score
    return round(total_score, 2)

def generate_mock_data(num_engineers=10):
    data = []
    for _ in range(num_engineers):
        input_tokens = random.randint(50000, 400000)
        # Cap cache reads to maintain a realistic upper bound against input tokens
        cache_read_tokens = random.randint(0, int(input_tokens * 0.9))
        
        # Calculate realistic model mix summing to ~1.0
        opus = random.uniform(0.0, 0.4)
        sonnet = random.uniform(0.3, 0.8)
        haiku = max(0.0, 1.0 - opus - sonnet)
        
        total = opus + sonnet + haiku
        
        engineer = {
            "user_id": fake.uuid4(),
            "name": fake.name(),
            "date": str(date.today()),
            "input_tokens": input_tokens,
            "output_tokens": random.randint(10000, 80000),
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": random.randint(5000, 50000),
            "model_mix": {
                "opus_pct": round(opus / total, 2),
                "sonnet_pct": round(sonnet / total, 2),
                "haiku_pct": round(haiku / total, 2)
            },
            "session_count": random.randint(1, 8),
            "compact_uses": random.randint(0, 5),
            "git_commits": random.randint(0, 12),
            "estimated_cost_usd": round(random.uniform(5.0, 30.0), 2)
        }
        data.append(engineer)
    
    # Save to the root directory for easy access in Phase 1
    file_path = "engineers_data.json"
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)
    
    return data

if __name__ == "__main__":
    generate_mock_data()
    print("Successfully generated engineers_data.json")