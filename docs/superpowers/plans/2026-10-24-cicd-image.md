# ARES Independent CI and Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test every ARES PR and publish traceable images only after merge.

**Architecture:** One least-privilege CI workflow tests/builds PRs and publishes GHCR images on `master`; GonzaloOS later selects the immutable digest.

**Tech Stack:** GitHub Actions, uv, Docker Buildx, GHCR.

**Spec:** `docs/superpowers/specs/2026-10-24-cicd-image-design.md`

## Global Constraints

- No deployment or production secrets in ARES.
- No image publication from pull requests.
- Preserve offline/no-personal-data tests.

## Review Focus

- Draft PRs must still run CI.
- Package write access must be isolated to the publish job.
- PR container builds must use `push: false`.
- Published images must label the exact source revision.
- No mutable tag may be used by the production Compose contract.

---

### Task 1: PR tests and independent image publication

**Files:** `.github/workflows/ci.yml`, `Dockerfile`, `tests/test_cicd_contract.py`

- [ ] Write workflow contract tests and observe failure.
- [ ] Run tests on every PR and build without publishing.
- [ ] Publish a revision-labelled image only on `master`.
- [ ] Run the full offline suite.
