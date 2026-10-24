from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_pull_request_runs_tests_and_builds_without_publishing():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pull_request:" in workflow
    assert "types:" not in workflow
    assert "uv run pytest -q" in workflow
    assert "push: false" in workflow


def test_only_master_publish_job_receives_package_write_permission():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "branches: [master]" in workflow
    assert "packages: write" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "push: true" in workflow
    assert "attestations: write" in workflow and "id-token: write" in workflow
    assert "actions/attest-build-provenance@977bb373ede98d70efdf65b84cb5f73e068dcc2a" in workflow


def test_container_records_exact_revision_label():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "ARG VCS_REF=unknown" in dockerfile
    assert 'org.opencontainers.image.revision="$VCS_REF"' in dockerfile
