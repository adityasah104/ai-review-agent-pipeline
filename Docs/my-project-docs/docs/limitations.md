---
sidebar_position: 7
title: Known Limitations
---

# Known Limitations

1. **Truncation risk on large files** — the current model (`amazon.nova-pro`) is used with `--edit-format whole` (full file rewrite) rather than `diff-fenced`, because it struggles to produce reliable diff blocks. On very large files this can hit the model's output token ceiling, occasionally causing silent deletion of code at the bottom of the file.

2. **Minor bugs occasionally missed alongside critical ones** — when a file has both a severe and a trivial issue, the model sometimes only fixes the severe one in a single pass and skips the minor one.

3. **No unit-test verification** — the CI loop currently only checks lint/syntax, not whether business logic still behaves correctly. `pytest` is not yet wired into the loop (see [Roadmap](/roadmap)).

4. **Headless — no dashboard** — unlike commercial tools (CodeRabbit, SonarQube), there is no UI for tracking trends over time; everything surfaces as PR comments.

5. **Limited repo-wide context** — relies on Aider's local file mapping rather than a full RAG index of the whole monorepo, so very deep architectural context can be missed on large codebases.

## Why the Whole-File Rewrite Strategy?

This is the single biggest source of limitation #1. The model struggles to consistently output perfect unified diffs (search/replace blocks), which is why the pipeline was forced to switch to rewriting the whole file with `--edit-format whole`. Diff-fenced editing would be safer for large files but currently produces malformed edits often enough to be unreliable. Upgrading the backend model is the recommended fix — see [Roadmap](/roadmap).

## Comparison to Existing PR Review Tools

There are several commercial tools that attempt to solve overlapping problems, including CodeRabbit, SonarQube, GitHub Copilot PR Review, and Codium PR-Agent (used under the hood here).

### Where this project is stronger
Most existing tools fall into the "glorified chatbot" category — they scan the code and post markdown comments for a developer to manually accept, pull, and reformat. This project is a **true autonomous agent**: it checks out the workspace, applies the fixes, runs local linters, and uses a self-healing CI loop to guarantee the code works *before* human eyes ever see it.

### Where this project lags
- **UI and dashboards** — tools like CodeRabbit and SonarQube have enterprise web dashboards for tracking metrics and team performance over time. This project is a headless backend pipeline.
- **Context window awareness** — commercial tools like Sweep.dev use advanced RAG to map an entire repository's architecture before fixing a bug. This agent relies on Aider's local file mapping, which is excellent but can miss deep architectural context in massive monorepos.

See [Troubleshooting](/docs/troubleshooting) if you're running into one of these limitations in practice.