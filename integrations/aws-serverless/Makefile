include ../_infra/Makefile

# aws-serverless specific targets

CURSOR_RULES := $(wildcard ../../.cursor/rules/*.mdc)

.PHONY: copilot
copilot: $(CURSOR_RULES)
	@echo "Updating GitHub Copilot instructions from .cursor/rules..."
	@mkdir -p ../../.github
	@cat $(CURSOR_RULES) > ../../.github/copilot-instructions.md
	@echo "✓ GitHub Copilot instructions updated"
