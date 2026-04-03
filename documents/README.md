# Documentation Guide

This directory is the canonical home for application-level documentation.

## Reading order for implementation work

1. [`specification.md`](specification.md)
2. [`technical_documentation.md`](technical_documentation.md)
3. [`source_current_state.md`](source_current_state.md)
4. [`change_log.md`](change_log.md)

## Structure

- Core system docs
  - [`specification.md`](specification.md): source of truth for requirements and contracts
  - [`technical_documentation.md`](technical_documentation.md): architecture, data model, and maintenance guidance
  - [`source_current_state.md`](source_current_state.md): current implementation snapshot
  - [`change_log.md`](change_log.md): meaningful change history
- Setup and operations
  - [`setup/team_onboarding.md`](setup/team_onboarding.md): local setup, run, and test workflow
  - [`deployment/windows_server_docker_deployment.md`](deployment/windows_server_docker_deployment.md): shared-server Docker deployment runbook
  - [`deployment/gcp_cloud_run_rollout/README.md`](deployment/gcp_cloud_run_rollout/README.md): Cloud Run rollout document set index
- Archive
  - [`archive/provisional_allocation_plan.md`](archive/provisional_allocation_plan.md): closed planning note retained for history

## What stays outside this folder

- [`/README.md`](../README.md): repository entry point and quick start
- [`/backend/README.md`](../backend/README.md): backend-local commands and notes
- [`/frontend/README.md`](../frontend/README.md): frontend-local commands and notes
- `AGENTS.md`: repository workflow instructions for coding agents
- `secret_passwords.md`: sensitive local note, intentionally not treated as general documentation
