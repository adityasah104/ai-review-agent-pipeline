---
sidebar_position: 6
title: Safety Mechanisms
---

# Safety Mechanisms

This pipeline is designed to never silently corrupt code or loop forever.

## Infinite-Loop Guard

`cli.py` checks the actual author of the last commit on the source branch (not synthetic merge-commit metadata) and exits immediately if it was the agent itself — otherwise every agent commit would re-trigger a new pipeline run.

```python
source_commit = os.environ.get("SYSTEM_PULLREQUEST_SOURCECOMMITID")
if source_commit:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%an", source_commit],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to look up commit author for {source_commit}. "
            f"Git error: {result.stderr.strip()}. "
            "Refusing to proceed rather than risk re-running on our own commit."
        )

    author = result.stdout.strip()
    if author == AI_AGENT_AUTHOR_NAME:
        print("SAFEGUARD TRIGGERED: Infinite Loop Prevented")
        return
```

## Fail-Closed on Ambiguity

If the loop-guard can't determine the commit author, it **raises** rather than proceeding — "assume safe and continue" is exactly the failure mode that causes infinite loops. This requires the pipeline checkout to use `fetchDepth: 0` so the commit object is guaranteed to be present locally.

## Isolated Fix Branch

Fixes are never pushed to the developer's own branch — they land on `agent/<branch>` and are opened as a separate PR for the developer to review and merge in. The checkout step in `aider_llm_fix.py` aborts entirely if it can't confirm it's on the correct branch:

```python
try:
    checkout_result = subprocess.run(
        ["git", "checkout", agent_branch],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )
except subprocess.CalledProcessError as e:
    return {
        "aider_fix_applied": False,
        "aider_fix_summary": f"Git checkout of '{agent_branch}' failed — aborting to avoid editing the wrong branch.",
    }
```

## Per-File Validation Gate

Each file fix is checked against a lint-diff baseline (no *new* lint codes introduced) before being kept; files that fail are discarded individually rather than failing the whole run. A file is only kept with warnings if:

- it has a major/critical finding attached, **and**
- Aider actually made changes, **and**
- the file still passes a syntax-validity check (`_is_syntactically_valid`)

Otherwise the file is reverted with `git checkout -- <file>` and reported as skipped.

## Bounded Retries

Both the CI-fix loop (`AIDER_MAX_CI_RETRIES`, default `2`) and the local lint loop (`MAX_CI_LINT_ATTEMPTS`, default `3`) have hard caps and give up gracefully rather than looping forever. When the cap is hit, the pipeline continues to the review/comment stage instead of failing silently.

## Syntax-Validity Floor

Even if lint isn't perfectly clean, a fix for a major/critical finding is only kept if the file still parses — Python via `ast.parse`, SQL via `sqlfluff parse`.

## No Silent Pushes

The pipeline compares local vs. remote commit hashes before pushing, so it never force-pushes empty or redundant commits:

```python
if local_hash == remote_hash:
    # nothing to push — return early
    ...
```

See [Limitations](/docs/limitations) for the failure modes these guardrails don't yet fully cover.