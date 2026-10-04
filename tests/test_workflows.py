"""OPS-01: every GitHub Actions job honors its off switch (a repository variable).

Setting the variable to "false" (Settings -> Secrets and variables -> Actions -> Variables)
skips automatic runs; a manual "Run workflow" (workflow_dispatch) still runs. This test
stops a job added later from silently ignoring the switch.
"""
import pathlib

import pytest
import yaml

from tests.conftest import PROJECT_ROOT

WORKFLOWS = pathlib.Path(PROJECT_ROOT) / ".github" / "workflows"

# Each workflow file and the repository variable that switches it off.
SWITCHES = {
    "ci.yml": "CI_ENABLED",
    "scheduled-alerts.yml": "SCHEDULED_ALERTS_ENABLED",
}


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def expected_condition(variable):
    return f"vars.{variable} != 'false' || github.event_name == 'workflow_dispatch'"


def test_every_workflow_file_has_a_registered_switch():
    files = sorted(p.name for p in WORKFLOWS.glob("*.yml"))
    assert files == sorted(SWITCHES), "add new workflows to SWITCHES (and give their jobs the if: condition)"


@pytest.mark.parametrize("name, variable", sorted(SWITCHES.items()))
def test_every_job_has_its_off_switch(name, variable):
    jobs = load(name)["jobs"]

    assert jobs, f"{name} has no jobs"
    for job_name, job in jobs.items():
        assert job.get("if") == expected_condition(variable), \
            f"{name}: job '{job_name}' must have `if: {expected_condition(variable)}`"


@pytest.mark.parametrize("name", sorted(SWITCHES))
def test_manual_run_button_exists(name):
    # The switch keeps manual runs working, so every workflow must offer one.
    # (PyYAML reads the key `on:` as boolean True, a YAML 1.1 quirk.)
    triggers = load(name)[True]
    assert "workflow_dispatch" in triggers


@pytest.mark.parametrize("name", sorted(SWITCHES))
def test_workflows_request_least_privilege(name):
    permissions = load(name).get("permissions")
    assert permissions is not None, f"{name} must declare permissions explicitly"
    assert "write" not in str(permissions), f"{name} must not request write access"


def test_frontend_container_serves_app_routes_not_404():
    """Alert emails link to /runbook/<severity>/<id>: in the Docker image nginx must hand app
    routes to index.html (the default config answered 404 for any deep link)."""
    frontend = pathlib.Path(PROJECT_ROOT) / "frontend"
    dockerfile = (frontend / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY nginx.conf /etc/nginx/conf.d/default.conf" in dockerfile
    conf = (frontend / "nginx.conf").read_text(encoding="utf-8")
    assert "try_files $uri $uri/ /index.html;" in conf
