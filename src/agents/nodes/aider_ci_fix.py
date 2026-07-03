import subprocess
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings
from src.azure_client.auth import get_azure_devops_token

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """
    Called ONLY when CI failed.
    Uses Aider to fix the lint/SQL errors reported in the CI logs.
    Max retries enforced via ci_fix_attempts in state — no infinite loop.

    After Aider commits the fix to the feature branch, the graph loops back
    to ci_status to re-check. The loop exits when:
      - CI passes, OR
      - ci_fix_attempts >= AIDER_MAX_CI_RETRIES (gives up, continues to review)
    """
    attempts = state.ci_fix_attempts + 1
    max_retries = settings.AIDER_MAX_CI_RETRIES

    log.info("aider_ci_fix_start", attempt=attempts, max=max_retries)

    if attempts > max_retries:
        # HARD STOP — do not loop again. Continue to LLM review anyway.
        log.warning("aider_ci_fix_max_retries_reached", attempts=attempts)
        return {
            "ci_fix_attempts": attempts,
            "ci_passed": True,  # Force continue — CI failures will be noted in review
            "status": "CI_FIX_GAVE_UP",
        }

    repo_path = settings.DEMO_REPO_PATH
    branch = state.source_branch.replace("refs/heads/", "")
    log_summary = state.ci_log_summary



    # Get the list of files that changed in this PR (only .py and .sql)
    changed_file_paths = [f["path"].lstrip("/") for f in state.changed_files]
    if not changed_file_paths:
        log.info("aider_ci_fix_no_files")
        return {"ci_fix_attempts": attempts, "ci_passed": True}

    try:
        # Switch to the feature branch in the demo repo
        token = await get_azure_devops_token()
        subprocess.run(
            ["git", "checkout", branch],
            cwd=repo_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}", "pull", "origin", branch],
            cwd=repo_path, check=True, capture_output=True,
        )

        # ---------------------------------------------------------
        # Process ONE file at a time — same pattern as aider_llm_fix.
        # Each file gets its own Aider call so we never blow the token limit.
        # ---------------------------------------------------------
        files_fixed = []

        for file_path in changed_file_paths:
            log.info("aider_ci_fix_file_start", file=file_path, attempt=attempts)

            if file_path.endswith(".sql"):
                # Fast path for SQL: Just use sqlfluff auto-fix, don't waste expensive AI tokens
                log.info("aider_ci_fix_sqlfluff_only", file=file_path)
                subprocess.run(
                    ["sqlfluff", "fix", file_path, "--dialect", "ansi", "--templater", "jinja", "--force"],
                    cwd=repo_path, capture_output=True
                )
                files_fixed.append(file_path)
                continue

            file_prompt = f"""The CI pipeline failed on branch '{branch}'. Here are the error logs:

{log_summary}

Fix only the issues in the file `{file_path}` reported above. Rules:
- Only edit `{file_path}`. Do NOT touch any other file.
- Fix Ruff errors only.
- Do NOT change business logic or add new features.
- Ensure the file remains syntactically valid after your changes.
"""

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
                timeout=150,
            )
            log.info("aider_ci_fix_file_output", file=file_path, returncode=result.returncode, stdout=result.stdout[-300:])

            # Run ruff auto-fix after each file
            subprocess.run(["ruff", "format", "."], cwd=repo_path, capture_output=True)
            subprocess.run(["ruff", "check", "--fix", "--unsafe-fixes", "."], cwd=repo_path, capture_output=True)

            files_fixed.append(file_path)

        # Commit all fixes in one commit
        subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)

        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_path, capture_output=True,
        )

        if diff_result.returncode != 0:
            commit_msg = f"fix(ci): aider auto-fix CI lint failures (attempt {attempts})"
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=repo_path, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}", "push", "origin", branch],
                cwd=repo_path, check=True, capture_output=True,
            )
            log.info("aider_ci_fix_committed", branch=branch, attempt=attempts)
        else:
            log.info("aider_ci_fix_no_changes_made")

        return {
            "ci_fix_attempts": attempts,
            "ci_passed": False,  # Will re-check CI status in next node
            "status": f"CI_FIX_ATTEMPT_{attempts}",
        }

    except subprocess.TimeoutExpired:
        log.error("aider_ci_fix_timeout")
        return {"ci_fix_attempts": attempts, "ci_passed": True, "status": "CI_FIX_TIMEOUT"}
    except Exception as e:
        log.error("aider_ci_fix_error", error=str(e))
        return {"ci_fix_attempts": attempts, "ci_passed": True, "status": "CI_FIX_ERROR"}