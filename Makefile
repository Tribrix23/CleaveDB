# CleaveDB3 - Build System
# ========================
#
# SAFETY: This Makefile only compiles code and runs tests.
# It does NOT modify system files, install system services, or touch anything
# outside the dsc/ directory.
#
# Usage:
#   make storage      - Build the Rust storage engine
#   make storage-test - Run Rust storage tests
#   make clean        - Remove build artifacts

.PHONY: storage storage-test clean help

# Default target
help:
	@echo "CleaveDB3 Build Targets:"
	@echo "  make storage       - Build Rust storage engine"
	@echo "  make storage-test  - Run Rust storage engine tests"
	@echo "  make clean         - Remove build artifacts"

# ── Rust Storage Engine ─────────────────────────────────────
CARGO = cargo

storage:
	cd storage && $(CARGO) build --release

storage-test:
	cd storage && $(CARGO) test -- --nocapture

storage-bench:
	cd storage && $(CARGO) bench

# ── Cleanup ─────────────────────────────────────────────────
clean:
	cd storage && $(CARGO) clean
