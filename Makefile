# Voron 2.611 — local CI parity.
# `make test` runs everything CI runs (klippy job requires Linux).
# `make test-py` runs the macOS-friendly subset (no klippy).

PYTHON      := .venv/bin/python
PRECOMMIT   := .venv/bin/pre-commit
# config/chopper_tune.cfg excluded: Pi-side symlink to a third-party file
# (~/chopper-resonance-tuner/chopper_tune.cfg) we don't own. Matches the
# exclusion in .github/workflows/ci.yml + .pre-commit-config.yaml.
CFGS        := $(filter-out config/chopper_tune.cfg, $(wildcard config/*.cfg)) \
               $(wildcard config/macros/*.cfg) \
               $(wildcard config/mmu/base/*.cfg) \
               $(wildcard config/mmu/addons/*.cfg) \
               $(wildcard config/mmu/optional/*.cfg)

# Layer 7 (one-shot) snapshots run inside a Linux Docker image because
# Klipper's chelper needs Linux kernel headers. See scripts/docker/layer7/.
LAYER7_IMG  := voron-2-611-layer7:py311
LAYER7_RUN  := docker run --rm -v $(PWD):/work -w /work $(LAYER7_IMG)

.PHONY: test test-py klippy refcheck pytest precommit builtins venv help \
        snapshot-image snapshot-before snapshot-after snapshot-diff

help:
	@echo "Targets:"
	@echo "  test            — full pipeline (klippy + refcheck + pytest + pre-commit). Linux only."
	@echo "  test-py         — refcheck + pytest + pre-commit. Works on macOS."
	@echo "  klippy          — run Klipper's test_klippy.py against tests/voron-2-611.test."
	@echo "  refcheck        — run scripts/macro_refcheck.py against all .cfg files."
	@echo "  pytest          — run scripts unit tests."
	@echo "  precommit       — run pre-commit hooks (text hygiene, ruff)."
	@echo "  builtins        — regenerate tests/builtins.txt from vendor/klipper."
	@echo "  venv            — bootstrap .venv/ if missing."
	@echo "  snapshot-image  — build Layer 7 Docker harness image."
	@echo "  snapshot-before — capture pre-refactor macro behavior snapshot (uses Docker)."
	@echo "  snapshot-after  — capture post-refactor macro behavior snapshot (uses Docker)."
	@echo "  snapshot-diff   — whitespace-insensitive diff of before/after snapshots."

# Full pipeline. Includes klippy → fails on macOS (Klipper chelper needs Linux headers).
test: venv klippy refcheck pytest precommit

# macOS-friendly subset.
test-py: venv refcheck pytest precommit

klippy: venv
	cd vendor/klipper && ../../$(PYTHON) scripts/test_klippy.py -d ../../tests/dict ../../tests/voron-2-611.test

refcheck: venv
	$(PYTHON) scripts/macro_refcheck.py $(CFGS)

pytest: venv
	$(PYTHON) -m pytest tests/ -v

precommit: venv
	$(PRECOMMIT) run --all-files

# Regenerate the Klipper builtins list. Run when bumping vendor/klipper.
builtins: venv
	@{ \
	  echo "# Auto-generated list of Klipper built-in gcode commands."; \
	  echo "# Source: cmd_<NAME>_help = ... declarations across vendor/klipper/klippy/"; \
	  echo "# Regenerate: \`make builtins\`"; \
	  grep -rhE "^[[:space:]]*cmd_[A-Z][A-Z0-9_]+_help[[:space:]]*=" vendor/klipper/klippy/ \
	    | sed -E 's/^[[:space:]]*cmd_([A-Z][A-Z0-9_]+)_help.*/\1/' \
	    | sort -u; \
	} > tests/builtins.txt
	@echo "Wrote $$(( $$(wc -l < tests/builtins.txt) - 3 )) commands to tests/builtins.txt"

venv: .venv/bin/pre-commit

.venv/bin/pre-commit: requirements.txt
	@if [ ! -d .venv ]; then python3 -m venv .venv; fi
	.venv/bin/pip install -q -r requirements.txt
	@touch $@

# Klipper's own runtime deps (greenlet, cffi, jinja2, scipy, etc.) are
# CI-only: `make klippy` can't run on macOS (Klipper chelper needs Linux
# kernel headers), so installing them locally just causes scipy build
# failures with no benefit. CI installs them in the klippy job.

# Layer 7 Docker harness — one-shot behavior diff for refactor PRs.
# Build context is vendor/klipper/scripts/ so the Dockerfile's COPY
# pulls klippy-requirements.txt + tests-requirements.txt directly.
snapshot-image:
	docker build -f scripts/docker/layer7/Dockerfile -t $(LAYER7_IMG) vendor/klipper/scripts

snapshot-before: snapshot-image
	$(LAYER7_RUN) python scripts/macro_behavior_diff.py before

snapshot-after: snapshot-image
	$(LAYER7_RUN) python scripts/macro_behavior_diff.py after

snapshot-diff:
	diff -w tests/snapshots/macro_behavior_before.txt tests/snapshots/macro_behavior_after.txt
