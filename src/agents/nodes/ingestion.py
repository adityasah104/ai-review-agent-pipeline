import subprocess
import structlog
from src.agents.state import PRReviewState
from src.azure_client.pr_client import get_pr_diff, get_file_content
from src.config.settings import settings
from src.azure_client.auth import get_azure_devops_token
from src.azure_client.pr_client import get_pr_diff, get_file_content, get_pr_metadata

log = structlog.get_logger()
MAX_CI_LINT_ATTEMPTS = 3

async def run(state: PRReviewState) -> dict:
    """
    Phase 2: Creates agent/<developer-branch>, applies Aider fixes there,
    runs local lint CI up to 3 times, then returns.
    Developer branch is NEVER touched.
    """
    active_findings = state.refined_findings if state.refined_findings else state.findings
    log.info("aider_llm_fix_start", findings_count=len(active_findings))

    fixable_findings = [
        f for f in active_findings
        if str(f.get("severity", "")).lower() in ("minor", "major", "critical")
        and str(f.get("category", "")).lower() in ("code_quality", "performance", "security")
        and float(f.get("confidence", 0.0)) >= settings.MIN_FIX_CONFIDENCE
    ]

    if not fixable_findings:
        log.info("aider_llm_fix_nothing_to_fix")
        return {"aider_fix_applied": False, "aider_fix_summary": "No auto-fixable issues found.", "agent_branch": ""}

    repo_path = settings.DEMO_REPO_PATH
    developer_branch = state.source_branch.replace("refs/heads/", "")

    # ------------------------------------------------------------------
    # STEP A: Derive the agent branch name — always "agent/<dev-branch>"
    # ------------------------------------------------------------------
    agent_branch = f"agent/{developer_branch}"

    files_to_fix = list(set(
        f["file_path"].lstrip("/") for f in fixable_findings if f.get("file_path")
    ))
    if not files_to_fix:
        return {"aider_fix_applied": False, "aider_fix_summary": "No files to fix.", "agent_branch": ""}

    try:
        token = await get_azure_devops_token()

        # ------------------------------------------------------------------
        # STEP B: Create agent branch in ADO from tip of developer_branch
        # ------------------------------------------------------------------
        from src.azure_client.pr_client import create_branch
        try:
            created = await create_branch(state.repository_id, agent_branch, developer_branch)
            log.info("agent_branch_created", branch=agent_branch, success=created)
        except Exception as e:
            # Branch may already exist — that is fine, push will update it
            log.warning("agent_branch_create_warning", branch=agent_branch, error=str(e))

        # ------------------------------------------------------------------
        # STEP C: Fetch and checkout the agent branch LOCALLY
        # ------------------------------------------------------------------
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
             "fetch", "origin", f"{agent_branch}:{agent_branch}"],
            cwd=repo_path, check=False, capture_output=True,
        )
        subprocess.run(["git", "checkout", agent_branch], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
             "pull", "origin", agent_branch, "--rebase"],
            cwd=repo_path, check=False, capture_output=True,
        )

        # ------------------------------------------------------------------
        # STEP D: Apply Aider fixes — ONE file at a time
        # ------------------------------------------------------------------
        files_fixed = []
        files_skipped = []
        files_kept_with_warnings = []

        for file_path in files_to_fix:
            file_findings = [
                f for f in fixable_findings
                if f.get("file_path", "").lstrip("/") == file_path
            ]
            file_instructions = [
                f"{i}. ({f.get('line_number', '')}): {f.get('suggestion', f.get('description', ''))}"
                for i, f in enumerate(file_findings, 1)
            ]

            base_file_prompt = f"""You are a precise, conservative code-fixing assistant working on exactly ONE file.

First, read the current content of `{file_path}` carefully before changing anything.
Locate each issue by matching its description to the actual current code.

Fix ONLY the following issues in `{file_path}`:

{chr(10).join(file_instructions)}

Rules:
1. Only edit `{file_path}`. Do NOT touch any other file.
2. Make ONLY the minimal change needed to resolve each listed issue.
3. If an issue does not match the current code, SKIP it.
4. Security issues are highest priority — real remediation, never lint suppression.
5. Keep all existing business logic and function signatures intact.
6. File must remain syntactically valid after your changes.
7. Code must pass ruff check and sqlfluff lint cleanly.
"""
            log.info("aider_llm_fix_file_start", file=file_path)
            is_sql = file_path.endswith(".sql")
            baseline_ruff = set() if is_sql else _ruff_codes(repo_path, file_path)
            baseline_sqlfluff = _sqlfluff_codes(repo_path, file_path) if is_sql else set()
            fixed = False
            feedback = ""

            for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
                prompt = base_file_prompt
                if feedback:
                    prompt += (
                        f"\n\nYour previous attempt introduced NEW lint errors:\n{feedback}\n\n"
                        "Fix these without reintroducing the original issue."
                    )
                aider_cmd = [
                    "aider", "--yes", "--no-gui", "--no-show-release-notes",
                    "--no-show-model-warnings", "--no-check-update",
                    "--no-auto-commits", "--no-stream", "--no-git",
                    "--map-tokens", "1024", "--edit-format", "diff",
                    "--lint-cmd", "python: ruff check", "--auto-lint",
                    "--model", "bedrock/amazon.nova-pro-v1:0",
                    "--message", prompt, file_path,
                ]
                result = subprocess.run(
                    aider_cmd, cwd=repo_path, capture_output=True,
                    text=True, timeout=300, stdin=subprocess.DEVNULL,
                )
                log.info("aider_llm_fix_file_output", file=file_path, attempt=attempt, returncode=result.returncode)
                subprocess.run(["ruff", "format", file_path], cwd=repo_path, capture_output=True)
                subprocess.run(["ruff", "check", "--fix", "--unsafe-fixes", file_path], cwd=repo_path, capture_output=True)
                if is_sql:
                    subprocess.run(
                        ["sqlfluff", "fix", file_path, "--dialect", "ansi", "--templater", "jinja", "--force"],
                        cwd=repo_path, capture_output=True,
                    )
                new_ruff = set() if is_sql else _ruff_codes(repo_path, file_path)
                new_sqlfluff = _sqlfluff_codes(repo_path, file_path) if is_sql else set()
                introduced_ruff = new_ruff - baseline_ruff
                introduced_sqlfluff = new_sqlfluff - baseline_sqlfluff
                if not introduced_ruff and not introduced_sqlfluff:
                    files_fixed.append(file_path)
                    fixed = True
                    log.info("aider_llm_fix_file_passed", file=file_path, attempt=attempt)
                    break
                feedback = (
                    f"Ruff codes newly introduced: {sorted(introduced_ruff)}\n"
                    f"Sqlfluff codes newly introduced: {sorted(introduced_sqlfluff)}"
                )
                log.warning("aider_llm_fix_file_attempt_failed", file=file_path, attempt=attempt)

            if not fixed:
                has_major_critical = any(
                    str(f.get("severity", "")).lower() in ("major", "critical") for f in file_findings
                )
                if has_major_critical and _is_syntactically_valid(repo_path, file_path):
                    files_fixed.append(file_path)
                    files_kept_with_warnings.append(file_path)
                    log.warning("aider_llm_fix_file_kept_with_lint_warnings", file=file_path)
                else:
                    subprocess.run(["git", "checkout", "--", file_path], cwd=repo_path, capture_output=True)
                    subprocess.run(["git", "clean", "-fd", "--", file_path], cwd=repo_path, capture_output=True)
                    files_skipped.append(file_path)
                    log.error("aider_llm_fix_file_discarded_unparseable", file=file_path)

        # ------------------------------------------------------------------
        # STEP E: Commit the fixes to the AGENT branch
        # ------------------------------------------------------------------
        if files_fixed:
            subprocess.run(["git", "add", "--", *files_fixed], cwd=repo_path, check=True, capture_output=True)

        diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_path, capture_output=True)
        if diff_result.returncode == 0:
            summary = "Aider ran but found no changes to apply."
            log.info("aider_llm_fix_no_changes")
            return {"aider_fix_applied": False, "aider_fix_summary": summary, "agent_branch": agent_branch}

        commit_msg = (
            f"fix(ai-review): apply {len(fixable_findings)} auto-fix suggestion(s)\n\n"
            f"Applied by AI Review Agent using Aider + Amazon Bedrock Nova Pro.\n"
            f"Files fixed: {files_fixed}\nOriginal PR: {state.pr_url}"
        )
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, check=True, capture_output=True)

        # ------------------------------------------------------------------
        # STEP F: Local CI Loop — ruff + sqlfluff on whole repo, up to 3x
        # ------------------------------------------------------------------
        ci_passed = False
        for ci_attempt in range(1, MAX_CI_LINT_ATTEMPTS + 1):
            log.info("local_ci_check", attempt=ci_attempt)
            ruff_result = subprocess.run(["ruff", "check", "src/"], cwd=repo_path, capture_output=True, text=True)
            sqlfluff_result = subprocess.run(
                ["sqlfluff", "lint", "models/", "--dialect", "ansi", "--format", "human"],
                cwd=repo_path, capture_output=True, text=True,
            )
            ruff_ok = ruff_result.returncode == 0
            sqlfluff_ok = sqlfluff_result.returncode == 0
            log.info("local_ci_result", attempt=ci_attempt, ruff_ok=ruff_ok, sqlfluff_ok=sqlfluff_ok)

            if ruff_ok and sqlfluff_ok:
                ci_passed = True
                log.info("local_ci_passed", attempt=ci_attempt)
                break

            if ci_attempt < MAX_CI_LINT_ATTEMPTS:
                ci_errors = ""
                if not ruff_ok:
                    ci_errors += f"=== Ruff errors ===\n{ruff_result.stdout}\n"
                if not sqlfluff_ok:
                    ci_errors += f"=== SQLFluff errors ===\n{sqlfluff_result.stdout}\n"
                log.warning("local_ci_failed_retrying", attempt=ci_attempt)

                for file_path in files_fixed:
                    ci_prompt = f"""The local lint CI failed after your fix on branch '{agent_branch}'.
Errors:
{ci_errors}
Fix only issues in `{file_path}` reported above.
- Only edit `{file_path}`. Do NOT touch any other file.
- Fix lint errors only. Do NOT change business logic.
- File must remain syntactically valid.
"""
                    aider_ci_cmd = [
                        "aider", "--yes", "--no-gui", "--no-show-release-notes",
                        "--no-show-model-warnings", "--no-check-update",
                        "--no-auto-commits", "--no-stream", "--no-git",
                        "--map-tokens", "0", "--edit-format", "diff",
                        "--lint-cmd", "python: ruff check", "--auto-lint",
                        "--model", "bedrock/amazon.nova-pro-v1:0",
                        "--message", ci_prompt, file_path,
                    ]
                    subprocess.run(aider_ci_cmd, cwd=repo_path, capture_output=True, text=True, timeout=150, stdin=subprocess.DEVNULL)
                    subprocess.run(["ruff", "format", file_path], cwd=repo_path, capture_output=True)
                    subprocess.run(["ruff", "check", "--fix", "--unsafe-fixes", file_path], cwd=repo_path, capture_output=True)

                subprocess.run(["git", "add", "-A"], cwd=repo_path, capture_output=True)
                diff_after = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_path, capture_output=True)
                if diff_after.returncode != 0:
                    subprocess.run(
                        ["git", "commit", "-m", f"fix(ci): lint fix attempt {ci_attempt}"],
                        cwd=repo_path, check=True, capture_output=True,
                    )
            else:
                log.warning("local_ci_max_attempts_reached", final_attempt=ci_attempt)

        # ------------------------------------------------------------------
        # STEP G: Push the agent branch to origin
        # ------------------------------------------------------------------
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}", "push", "origin", agent_branch],
            cwd=repo_path, check=True, capture_output=True,
        )
        log.info("agent_branch_pushed", branch=agent_branch, ci_passed=ci_passed)

        summary = (
            f"Fixed {len(files_fixed)} file(s) on branch `{agent_branch}`."
            + (f" {len(files_kept_with_warnings)} file(s) committed with lint warnings." if files_kept_with_warnings else "")
            + (f" Discarded {len(files_skipped)} file(s) as unparseable." if files_skipped else "")
            + (" Local CI passed." if ci_passed else f" Local CI still failing after {MAX_CI_LINT_ATTEMPTS} attempts — PR raised anyway.")
        )
        return {"aider_fix_applied": True, "aider_fix_summary": summary, "agent_branch": agent_branch}

    except subprocess.TimeoutExpired:
        log.error("aider_llm_fix_timeout")
        return {"aider_fix_applied": False, "aider_fix_summary": "Aider timed out.", "agent_branch": agent_branch}
    except Exception as e:
        log.error("aider_llm_fix_error", error=str(e))
        return {"aider_fix_applied": False, "aider_fix_summary": f"Aider error: {e}", "agent_branch": agent_branch}