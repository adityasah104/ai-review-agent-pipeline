---
sidebar_position: 5
title: Customization
---

# Customizing Review Behavior

| What you want to change | Where |
|---|---|
| What counts as a "changed file" | `ingestion.py` — file extension filter |
| What the LLM is allowed to flag | Edit `.md` files in `src/guidelines/` (e.g., `code_quality.md`, `security.md`, `performance.md`) |
| Auto-fix confidence threshold | `MIN_FIX_CONFIDENCE` env var |
| Which severities get auto-fixed | `aider_llm_fix.py` → `fixable_findings` filter |
| How many times the CI-fix loop retries | `AIDER_MAX_CI_RETRIES` env var / `MAX_CI_LINT_ATTEMPTS` constant |
| Coding style enforced during fixes | (Currently implicitly handled by Aider, you can pass custom lint rules via Ruff/SQLFluff config files) |
| PR comment formatting | `publish_review.py` → `_build_comment` / `_findings_table` |
| Agent PR branch naming (`agent/<branch>`) | `aider_llm_fix.py` → `agent_branch = f"agent/{developer_branch}"` |

## Generalizing to a New Language or Stack

The pipeline currently only reviews `.py` and `.sql` files with Ruff and SQLFluff. To adapt it:

### Step 1 — Extend the file filter

In `src/agents/nodes/ingestion.py`:

```python
if not (path.endswith(".py") or path.endswith(".sql")):
    continue
```

Extend this to whatever extensions your project uses, e.g. `.ts`, `.go`, `.java`.

### Step 2 — Swap the linters

Replace the linter invocations in three places:

- `ai-review.yml` — the "Standard CI Checks" step
- `aider_llm_fix.py` — `_ruff_codes`, `_sqlfluff_codes`, `_is_syntactically_valid`
- `aider_ci_fix.py` — the per-file fix loop

with the equivalent tool for your stack (e.g. `eslint --fix`, `golangci-lint run --fix`, `checkstyle`).

The underlying pattern — capture baseline lint codes, apply the fix, diff the new lint codes against the baseline, only keep the change if no *new* issues were introduced — is language-agnostic and should be preserved regardless of which linter you plug in.

### Step 3 — Inject Team-Specific Guidelines

The AI reviewers are fully abstracted! Instead of hardcoding language-specific rules directly into the backend code, the architecture dynamically loads **Modular Guidelines**. 

The base prompts handle the generic LLM formatting instructions, but you simply drop your team's custom `.md` files into the `src/guidelines/` folder. The corresponding agent dynamically reads the file matching its category and injects it into its prompt at runtime.

Available guideline files to override:
- `src/guidelines/code_quality.md`
- `src/guidelines/security.md`
- `src/guidelines/performance.md`

Example of what you can put in `code_quality.md`:
```text
- Severe logic errors, unhandled exceptions, or broken functionality
- Missing context manager (with block) on file open() or similar resources
- Mutable default arguments in function definitions (e.g. def foo(x=[]))
- Bare print() statements (should use logging instead)
- Missing return type annotations on new functions
```

This ensures that the underlying Python agent code remains identical across all projects, while the team's specific coding guidelines (TypeScript rules, Java rules, etc.) are fully modular and customizable by simply replacing the markdown files.

Continue to [Safety Mechanisms](/docs/safety) to see how these customizations interact with the pipeline's guardrails.