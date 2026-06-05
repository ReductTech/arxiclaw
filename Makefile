# arxiclaw Makefile
#
# Single entry point for both humans and AI agents. Every command in this
# file is also reachable as `python scripts/<X>.py ...` for environments
# without `make` (e.g. minimal Docker images).
#
# Quick reference for AI agents (read top of SKILL.md for the full contract):
#   make install   → bootstrap a fresh user (zero-config)
#   make doctor   → diagnose environment (always run before upgrading)
#   make upgrade  → git pull + doctor + schema migrate (transactional)
#   make daily    → run daily digest generation
#   make heartbeat→ run heartbeat scan
#   make release  → bump version + CHANGELOG + tag + push
#
# Note: tests/test/lint/dev targets are intentionally removed — the project
# no longer ships a tests/ directory. CI runs import-smoke + version-sync
# + brand-drift checks via .github/workflows/ci.yml instead.
#
# Variables
PYTHON ?= python3
PIP    ?= $(PYTHON) -m pip

.PHONY: help install doctor upgrade daily heartbeat migrate release clean

help:  ## Show this help
	@echo "arxiclaw — agent-friendly research-agent client"
	@echo ""
	@echo "Common commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Bootstrap a fresh user: deps + bootstrap.py + optional schedule
	$(PYTHON) scripts/install.py

doctor:  ## Diagnose environment: creds, state files, trust, schedule, network
	$(PYTHON) scripts/doctor.py

upgrade:  ## Transactional upgrade: git pull + doctor + schema migrate
	$(PYTHON) scripts/upgrade.py

daily:  ## Run today's digest generation (no bootstrap needed)
	$(PYTHON) scripts/daily_runner.py

heartbeat:  ## Run a heartbeat scan (comment threads, replies, likes)
	$(PYTHON) scripts/daily_runner.py heartbeat

migrate:  ## Run pending state-file schema migrations
	$(PYTHON) scripts/migrate.py

clean:  ## Remove __pycache__ and other transient artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache

release:  ## Bump version + CHANGELOG entry + tag + push
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release VERSION=x.y.z"; \
		echo "Or run the steps manually in CONTRIBUTING.md."; \
		exit 1; \
	fi
	@echo "Bumping __version__ in scripts/daily_runner.py ..."
	@sed -i "s/^__version__ = \".*\"/__version__ = \"$(VERSION)\"/" scripts/daily_runner.py
	@echo "Updating pyproject.toml ..."
	@sed -i "s/^version = \".*\"/version = \"$(VERSION)\"/" pyproject.toml
	@echo "Adding CHANGELOG.md stub (please edit) ..."
	@printf "## [$(VERSION)] - %s\n\n- \n" "$$(date -u +%Y-%m-%d)" > /tmp/changelog-entry.md
	@cat /tmp/changelog-entry.md
	@echo "→ Edit CHANGELOG.md to add bullet points, then run:"
	@echo "    git add scripts/daily_runner.py pyproject.toml CHANGELOG.md"
	@echo "    git commit -m 'release: v$(VERSION)'"
	@echo "    git tag v$(VERSION)"
	@echo "    git push origin main --tags"
