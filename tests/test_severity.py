import pytest

from core.severity import severity_for_rank


@pytest.mark.parametrize("rank, team_size, expected", [
    (1, 10, "low"), (5, 10, "low"), (6, 10, "moderate"), (8, 10, "moderate"),
    (9, 10, "critical"), (10, 10, "critical"),
    (3, 3, "low"),                       # small team: nobody is critical (documented quirk)
    (7, 7, "critical"), (6, 7, "critical"),
    (6, 20, "moderate"), (19, 20, "critical"),
])
def test_severity_tiers(rank, team_size, expected):
    assert severity_for_rank(rank, team_size) == expected
