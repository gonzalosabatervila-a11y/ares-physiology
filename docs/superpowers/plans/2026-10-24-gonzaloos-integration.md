# GonzaloOS Prefix Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing ARES UI safe and functional at `/ares/` while retaining standalone development.

**Architecture:** Relative browser URLs plus a configurable public base path. The private server keeps all existing API routes and verifies the Caddy authorization marker for writes.

**Tech Stack:** FastAPI, DuckDB, vanilla JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-10-24-gonzaloos-integration-design.md`

## Global Constraints

- Preserve the single DuckDB writer and every validated Scientific Atelier view.
- No external data or provider calls.
- No secrets or personal paths in Git.

## Review Focus

- Standalone `/` remains compatible.
- `/ares/` resource and API URLs stay under the prefix.
- Proxied writes need authorization and CSRF; forged public headers are neutralized by Caddy.
- Empty DuckDB renders honest empty states.
- Return navigation never leaks state or opens an unsafe origin.

---

### Task 1: Prefix-safe browser assets and APIs

- [ ] Write failing static/server tests for relative URLs and prefixed manifest.
- [ ] Implement relative assets/API helper and dynamic manifest.
- [ ] Run focused and full pytest suites.

### Task 2: Proxy write contract

- [ ] Write failing tests for missing authorization/CSRF and valid proxy request.
- [ ] Extend the existing LAB guard without weakening standalone localhost mode.
- [ ] Run security regression tests and full suite.

### Task 3: Container and operations

- [ ] Add non-root Docker image, healthcheck, synthetic startup documentation and secret-file contract.
- [ ] Add backup/restore/rollback runbook without touching real data.
- [ ] Run image/config checks available locally.
