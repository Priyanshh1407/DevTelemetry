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
