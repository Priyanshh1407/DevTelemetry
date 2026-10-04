"""BUG-04: the console agent (main.py) works from the same database as the dashboard."""
import os
import subprocess
import sys

from tests.conftest import PROJECT_ROOT


def test_agent_ranks_the_engineers_in_the_database(seeded_db, capsys, mock_gemini):
    import main

    main.main()
    out = capsys.readouterr().out

    lines = [line for line in out.splitlines() if line.startswith(("1 ", "10 "))]
    assert "Engineer 09" in lines[0]          # best in the fixture DB
    assert "Engineer 00" in lines[-1]         # worst in the fixture DB
    assert "Coaching for Engineer 00" in out  # guides go to the bottom of the leaderboard


def test_agent_never_sends_email_addresses_to_the_llm(seeded_db, mock_gemini):
    import main

    main.main()

    prompts = " ".join(str(call) for call in mock_gemini.models.generate_content.call_args_list)
    assert "@example.com" not in prompts
    assert "Engineer 0" not in prompts  # names are identity too


def test_agent_runs_on_a_fresh_clone(tmp_path):
    # Fresh clone: no database, no engineers_data.json, no API key. It must seed and run.
    env = {**os.environ, "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "", "DB_PATH": str(tmp_path / "fresh.db"),
           "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "main.py")], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=180)

    assert result.returncode == 0, result.stderr[-2000:]
    assert "EFFICIENCY LEADERBOARD" in result.stdout
    assert "fallback guide: unavailable" in result.stdout  # no key: AI degrades, the agent still runs
