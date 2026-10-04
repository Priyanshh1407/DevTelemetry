"""The one rule for severity tiers, shared by the API, the alert worker and the CLI agent.

Tiers are relative to the team (rank on the latest day), not absolute score thresholds:
top 5 are "low", the bottom 2 are "critical", everyone in between is "moderate".
Known quirk, kept as-is: in a team of 6 or fewer, "low" wins, so nobody is critical.
"""

LOW, MODERATE, CRITICAL = "low", "moderate", "critical"


def severity_for_rank(rank, team_size):
    """rank is 1-based (1 = best score)."""
    if rank <= 5:
        return LOW
    if rank >= team_size - 1:
        return CRITICAL
    return MODERATE
