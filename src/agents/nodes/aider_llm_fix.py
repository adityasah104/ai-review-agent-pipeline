import subprocess
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings
from src.azure_client.auth import get_azure_devops_token

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """
    Uses Aider to apply fixes suggested by the LLM review agents.
    Only fixes minor and major findings — skips critical (too risky to auto-fix).
    Commits to the feature branch. Does NOT merge to main.
    """
    # Use PR-Agent's refined findings if available, otherwise fall back to raw findings
    active_findings = state.refined_findings if state.refined_findings else state.findings
    log.info("aider_llm_fix_start", findings_count=len(active_findings))

    # Filter: auto-fix minor, major, and critical that meet confidence threshold
    fixable_findings = [
        f for f in active_findings
        if f.get("severity") in ("minor", "major", "critical")
        and f.get("category") in ("code_quality", "performance", "security")
        and float(f.get("confidence", 0.0)) >= settings.MIN_FIX_CONFIDENCE
    ]

    if not fixable_findings:
        log.info("aider_llm_fix_nothing_to_fix")
        return {"aider_fix_applied": False, "aider_fix_summary": "No auto-fixable issues found."}

    # Build a clear instruction list for Aider
    fix_instructions = []
    for i, finding in enumerate(fixable_findings, 1):
        fix_instructions.append(
            f"{i}. In {finding.get('file_path', 'unknown')} "
            f"({finding.get('line_number', '')}): "
            f"{finding.get('suggestion', finding.get('description', ''))}"
        )

    aider_prompt = f"""
Apply the following code quality improvements to the changed files.

Instructions:
{chr(10).join(fix_instructions)}

Rules you must follow:
- Apply the suggested fixes safely without breaking existing business logic.
- Ensure all Python files remain syntactically valid after changes.
- Ensure all SQL files remain syntactically valid after changes.
"""

    repo_path = settings.DEMO_REPO_PATH
    branch = state.source_branch.replace("refs/heads/", "")

    # Get unique file paths that have fixable findings
    files_to_fix = list(set(
        f["file_path"].lstrip("/") for f in fixable_findings
        if f.get("file_path")
    ))

    if not files_to_fix:
        return {"aider_fix_applied": False, "aider_fix_summary": "No files to fix."}

    try:
        token = await get_azure_devops_token()
        # Make sure we're on the right branch
        subprocess.run(
            ["git", "checkout", branch],
            cwd=repo_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}", "pull", "origin", branch],
            cwd=repo_path, check=True, capture_output=True,
        )

        # ---------------------------------------------------------
        # LAYER 2: Process ONE file at a time
        # Each file gets its own Aider call + validation gate.
        # If one file breaks, only that file is discarded —
        # the rest are still committed safely.
        # ---------------------------------------------------------
        files_fixed = []
        files_skipped = []

        for file_path in files_to_fix:

            # Build a targeted prompt for THIS file only
            file_findings = [
                f for f in fixable_findings
                if f.get("file_path", "").lstrip("/") == file_path
            ]
            file_instructions = []
            for i, finding in enumerate(file_findings, 1):
                file_instructions.append(
                    f"{i}. ({finding.get('line_number', '')}): "
                    f"{finding.get('suggestion', finding.get('description', ''))}"
                )

            file_prompt = f"""Fix the following issues in the file `{file_path}`:

{chr(10).join(file_instructions)}

Rules:
- Only edit `{file_path}`. Do NOT touch any other file.
- Keep all existing business logic intact.
- Ensure the file remains syntactically valid after your changes.
"""

            log.info("aider_llm_fix_file_start", file=file_path)

            aider_cmd = [
                "aider",
                "--yes",
                "--no-gui",
                "--no-show-release-notes",
                "--no-show-model-warnings",
                "--no-check-update",
                "--no-auto-commits",
                "--no-stream",
                "--no-git",
                "--map-tokens", "0",
                "--edit-format", "diff",
                "--lint-cmd", "python: ruff check",
                "--auto-lint",
                "--model", "bedrock/amazon.nova-pro-v1:0",
                "--message", file_prompt,
                file_path,
            ]

            result = subprocess.run(
                aider_cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            log.info("aider_llm_fix_file_output", file=file_path, returncode=result.returncode)

            # Auto-format after each Aider run
            subprocess.run(["ruff", "format", "."], cwd=repo_path, capture_output=True)
            subprocess.run(["ruff", "check", "--fix", "--unsafe-fixes", "."], cwd=repo_path, capture_output=True)
            if file_path.endswith(".sql"):
                subprocess.run(
                    ["sqlfluff", "fix", "models/", "--dialect", "ansi", "--templater", "jinja", "--force"],
                    cwd=repo_path, capture_output=True
                )

            # --- Per-file Validation Gate ---
            ruff_result = subprocess.run(
                ["ruff", "check", "."], cwd=repo_path, capture_output=True, text=True
            )
            ruff_ok = ruff_result.returncode == 0

            # Only run sqlfluff validation for SQL files — Python files don't need it
            sqlfluff_ok = True
            if file_path.endswith(".sql"):
                sqlfluff_result = subprocess.run(
                    ["sqlfluff", "lint", "models/", "--dialect", "ansi", "--templater", "jinja"],
                    cwd=repo_path, capture_output=True, text=True
                )
                sqlfluff_ok = sqlfluff_result.returncode == 0

            if not ruff_ok or not sqlfluff_ok:
                # This file's changes broke something — discard ONLY this file
                log.error(
                    "aider_llm_fix_file_validation_failed",
                    file=file_path,
                    ruff_ok=ruff_ok,
                    sqlfluff_ok=sqlfluff_ok,
                    ruff_output=ruff_result.stdout[-300:],
                )
                subprocess.run(["git", "checkout", "--", file_path], cwd=repo_path, capture_output=True)
                subprocess.run(["git", "clean", "-fd"], cwd=repo_path, capture_output=True)
                files_skipped.append(file_path)
                log.warning("aider_llm_fix_file_discarded", file=file_path)
            else:
                files_fixed.append(file_path)
                log.info("aider_llm_fix_file_passed", file=file_path)

        # ---------------------------------------------------------
        # Commit all successfully validated files in one commit
        # ---------------------------------------------------------
        subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)

        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_path, capture_output=True,
        )

        if diff_result.returncode != 0:
            skipped_note = f"\nSkipped (hallucination detected): {files_skipped}" if files_skipped else ""
            commit_msg = (
                f"fix(ai-review): apply {len(fixable_findings)} auto-fix suggestion(s)\n\n"
                f"Applied by AI Review Agent using Aider + Amazon Bedrock Nova Pro.\n"
                f"Files fixed: {files_fixed}{skipped_note}\n"
                f"PR: {state.pr_url}"
            )
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=repo_path, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}", "push", "origin", branch],
                cwd=repo_path, check=True, capture_output=True,
            )
            summary = (
                f"✅ Fixed {len(files_fixed)} file(s): {files_fixed}."
                + (f" ⚠️ Skipped {len(files_skipped)} file(s) due to hallucination: {files_skipped}." if files_skipped else "")
            )
            log.info("aider_llm_fix_committed", branch=branch, fixed=files_fixed, skipped=files_skipped)
        else:
            summary = "ℹ️ Aider ran but found no changes to apply."
            log.info("aider_llm_fix_no_changes")

        return {"aider_fix_applied": True, "aider_fix_summary": summary}

    except subprocess.TimeoutExpired:
        log.error("aider_llm_fix_timeout")
        return {"aider_fix_applied": False, "aider_fix_summary": "⚠️ Aider timed out during fix."}
    except Exception as e:
        log.error("aider_llm_fix_error", error=str(e))
        return {"aider_fix_applied": False, "aider_fix_summary": f"⚠️ Aider error: {e}"}