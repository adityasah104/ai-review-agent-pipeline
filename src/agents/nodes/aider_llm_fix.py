import re
import os
import asyncio
import textwrap
import subprocess
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings
from src.azure_client.auth import get_azure_devops_token
from src.agents.prompts.aider_fix import build_aider_fix_prompt, build_ci_lint_prompt

log = structlog.get_logger()

# Max attempts per file: 1 initial try + up to this many feedback-corrected retries
MAX_FIX_RETRIES = 2
MAX_FIX_ATTEMPTS = MAX_FIX_RETRIES + 1

# Max times we run the whole-repo lint CI after committing
MAX_CI_LINT_ATTEMPTS = 3

_RUFF_CODE_RE = re.compile(r":\d+:\d+:\s+(\S+)")
_SQLFLUFF_CODE_RE = re.compile(r"\b(?:L\d{3}|[A-Z]{2}\d{2})\b")


def _ruff_codes(repo_path: str, file_path: str) -> set[str]:
    """Return the set of ruff rule codes currently present in a single file."""
    result = subprocess.run(
        ["ruff", "check", file_path], cwd=repo_path, capture_output=True, text=True
    )
    return set(_RUFF_CODE_RE.findall(result.stdout))


def _sqlfluff_codes(repo_path: str, file_path: str) -> set[str]:
    """Return the set of sqlfluff rule codes currently present in a single file."""
    result = subprocess.run(
        ["sqlfluff", "lint", file_path, "--dialect", "ansi", "--templater", "jinja"],
        cwd=repo_path, capture_output=True, text=True,
    )
    return set(_SQLFLUFF_CODE_RE.findall(result.stdout))


def _is_syntactically_valid(repo_path: str, file_path: str) -> bool:
    """
    Hard floor check: does the file at least parse? This is deliberately a much
    lower bar than passing lint — it only catches "this file is now broken and
    would fail to run/build," not style or convention issues. Used so that a
    genuine security/major fix isn't thrown away over a lint nit, while still
    guaranteeing we never keep a file that can't even parse.
    """
    full_path = f"{repo_path.rstrip('/')}/{file_path}"
    if file_path.endswith(".py"):
        try:
            import ast
            with open(full_path, "r", encoding="utf-8") as fh:
                ast.parse(fh.read())
            return True
        except (SyntaxError, OSError, UnicodeDecodeError):
            return False
    if file_path.endswith(".sql"):
        result = subprocess.run(
            ["sqlfluff", "parse", file_path, "--dialect", "ansi", "--templater", "jinja"],
            cwd=repo_path, capture_output=True, text=True,
        )
        return result.returncode == 0
    # Unknown file type — no parser available, assume valid rather than
    # discarding a fix we have no way to actually validate.
    return True


def run(state: PRReviewState) -> dict:
    """
    Phase 2: Creates agent/<developer-branch> in ADO, checks it out locally,
    applies Aider fixes there, runs local ruff+sqlfluff CI up to 3 times,
    then pushes. Developer branch is NEVER touched.
    """
    # Use PR-Agent's refined findings if available, otherwise fall back to raw findings
    active_findings = state.refined_findings if state.refined_findings else state.findings
    log.info("aider_llm_fix_start", findings_count=len(active_findings))

    import json
    log.info("active_findings_dump", findings=json.dumps(active_findings, indent=2))

    # Filter: auto-fix minor, major, and critical that meet confidence threshold
    fixable_findings = [
        f for f in active_findings
        if str(f.get("severity", "")).lower() in ("minor", "major", "critical")
        and str(f.get("category", "")).lower() in ("code_quality", "performance", "security", "bug")
        and float(f.get("confidence", 0.0)) >= settings.MIN_FIX_CONFIDENCE
    ]

    if not fixable_findings:
        log.info("aider_llm_fix_no_high_confidence_findings")

    repo_path = settings.DEMO_REPO_PATH
    developer_branch = state.source_branch.replace("refs/heads/", "")

    # ------------------------------------------------------------------
    # STEP A: Derive the agent branch name — always "agent/<dev-branch>"
    # ------------------------------------------------------------------
    agent_branch = f"agent/{developer_branch}"

    # Get unique file paths that have fixable findings (may be empty)
    files_to_fix = list(set(
        f["file_path"].lstrip("/") for f in fixable_findings
        if f.get("file_path")
    ))

    try:
        token = asyncio.run(get_azure_devops_token())

        # ------------------------------------------------------------------
        # STEP B: Create agent branch in ADO from tip of developer_branch
        # ------------------------------------------------------------------
        from src.azure_client.pr_client import create_branch
        try:
            created = asyncio.run(create_branch(state.repository_id, agent_branch, developer_branch))
            log.info("agent_branch_created", branch=agent_branch, success=created)
        except Exception as e:
            # Branch may already exist — that is fine, push will update it
            log.warning("agent_branch_create_warning", branch=agent_branch, error=str(e))

        # ------------------------------------------------------------------
        # STEP C: Fetch and checkout the agent branch LOCALLY
        # The fetch may fail (branch doesn't exist remotely yet) — that's OK.
        # The checkout MUST succeed — if it fails, we abort immediately rather
        # than letting Aider edit files on the wrong branch (e.g. main).
        # ------------------------------------------------------------------
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
             "fetch", "origin", f"{agent_branch}:{agent_branch}"],
            cwd=repo_path, check=False, capture_output=True,
        )
        try:
            checkout_result = subprocess.run(
                ["git", "checkout", agent_branch],
                cwd=repo_path, check=True, capture_output=True, text=True,
            )
            log.info("agent_branch_checked_out", branch=agent_branch)
        except subprocess.CalledProcessError as e:
            log.error(
                "agent_branch_checkout_failed",
                branch=agent_branch,
                stderr=e.stderr.strip(),
            )
            return {
                "aider_fix_applied": False,
                "aider_fix_summary": f"Git checkout of '{agent_branch}' failed — aborting to avoid editing the wrong branch. Error: {e.stderr.strip()}",
                "agent_branch": agent_branch,
            }
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
             "pull", "origin", agent_branch, "--rebase"],
            cwd=repo_path, check=False, capture_output=True,
        )

        # ---------------------------------------------------------
        # STEP D: Process ONE file at a time on the agent branch
        # Only runs if there are high-confidence LLM findings to fix.
        # Each file gets its own Aider call + validation gate.
        # If one file breaks, only that file is discarded —
        # the rest are still committed safely.
        # ---------------------------------------------------------
        files_fixed = []
        files_skipped = []
        files_kept_with_warnings = []

        if fixable_findings and files_to_fix:
            for file_path in files_to_fix:
                # Build a targeted prompt for THIS file only
                file_findings = [
                    f for f in fixable_findings
                    if f.get("file_path", "").lstrip("/") == file_path
                ]
                file_instructions = []
                import json
                for i, finding in enumerate(file_findings, 1):
                    finding_str = json.dumps(finding, indent=2)
                    file_instructions.append(f"--- ISSUE {i} ---\n{finding_str}\n")

                base_file_prompt = build_aider_fix_prompt(file_path, file_instructions)

                log.info("aider_llm_fix_file_start", file=file_path)

                is_sql = file_path.endswith(".sql")
                baseline_ruff = set() if is_sql else _ruff_codes(repo_path, file_path)
                baseline_sqlfluff = _sqlfluff_codes(repo_path, file_path) if is_sql else set()

                fixed = False
                feedback = ""
                aider_made_changes_overall = False

                for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
                    prompt = base_file_prompt
                    if feedback:
                        prompt += (
                            "\n\nYour previous attempt introduced NEW lint errors that were not "
                            f"present before your change:\n{feedback}\n\n"
                            "Fix these specific errors without reintroducing the original issue, "
                            "and without touching anything else in the file."
                        )

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
                        "--map-tokens", "1024",
                        "--edit-format", "whole",
                        "--lint-cmd", "python: ruff check",
                        "--auto-lint",
                        "--model", "bedrock/amazon.nova-pro-v1:0",
                        "--message", prompt,
                        file_path,
                    ]

                    result = subprocess.run(
                        aider_cmd,
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        stdin=subprocess.DEVNULL,
                    )
                    if result.returncode != 0:
                        log.error(
                            "aider_llm_fix_file_failed",
                            file=file_path, attempt=attempt, returncode=result.returncode,
                            stderr=result.stderr.strip(), stdout=result.stdout.strip()
                        )
                    else:
                        log.info(
                            "aider_llm_fix_file_output",
                            file=file_path, attempt=attempt, returncode=result.returncode,
                        )

                    diff_check = subprocess.run(["git", "diff", "--", file_path], cwd=repo_path, capture_output=True)
                    if diff_check.stdout.strip():
                        aider_made_changes_overall = True

                    subprocess.run(["ruff", "format", file_path], cwd=repo_path, capture_output=True)
                    subprocess.run(
                        ["ruff", "check", "--fix", "--unsafe-fixes", file_path],
                        cwd=repo_path, capture_output=True,
                    )
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
                        if aider_made_changes_overall:
                            files_fixed.append(file_path)
                            fixed = True
                            log.info("aider_llm_fix_file_passed", file=file_path, attempt=attempt)
                        else:
                            log.warning("aider_llm_fix_no_changes_made", file=file_path, attempt=attempt)
                        break

                    feedback = (
                        f"Ruff codes newly introduced: {sorted(introduced_ruff)}\n"
                        f"Sqlfluff codes newly introduced: {sorted(introduced_sqlfluff)}"
                    )
                    finding_severities = [str(f.get("severity", "")).lower() for f in file_findings]
                    log.warning(
                        "aider_llm_fix_file_attempt_failed",
                        file=file_path, attempt=attempt,
                        introduced_ruff=sorted(introduced_ruff),
                        introduced_sqlfluff=sorted(introduced_sqlfluff),
                        finding_severities=finding_severities,
                    )

                if not fixed:
                    has_major_critical = any(
                        str(f.get("severity", "")).lower() in ("major", "critical")
                        for f in file_findings
                    )
                    finding_severities = [str(f.get("severity", "")).lower() for f in file_findings]
                    if has_major_critical and aider_made_changes_overall and _is_syntactically_valid(repo_path, file_path):
                        files_fixed.append(file_path)
                        files_kept_with_warnings.append(file_path)
                        log.warning(
                            "aider_llm_fix_file_kept_with_lint_warnings",
                            file=file_path, remaining_issues=feedback,
                            finding_severities=finding_severities,
                        )
                    else:
                        subprocess.run(["git", "checkout", "--", file_path], cwd=repo_path, capture_output=True)
                        subprocess.run(["git", "clean", "-fd", "--", file_path], cwd=repo_path, capture_output=True)
                        files_skipped.append(file_path)
                        log.error(
                            "aider_llm_fix_file_discarded_unparseable",
                            file=file_path, last_feedback=feedback,
                            finding_severities=finding_severities,
                        )

        # end of `if fixable_findings and files_to_fix` block


        # ------------------------------------------------------------------
        # STEP E: Commit LLM fixes to the AGENT branch (only if changes exist)
        # ------------------------------------------------------------------
        if files_fixed:
            subprocess.run(["git", "add", "--", *files_fixed], cwd=repo_path, check=True, capture_output=True)

        llm_diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_path, capture_output=True,
        )

        if llm_diff.returncode != 0:
            # There are staged LLM fixes — commit them
            skipped_note = f"\nDiscarded (unparseable after retries): {files_skipped}" if files_skipped else ""
            warning_note = (
                f"\nCommitted with unresolved lint warnings: {files_kept_with_warnings}"
                if files_kept_with_warnings else ""
            )
            commit_msg = (
                f"fix(ai-review): apply {len(fixable_findings)} auto-fix suggestion(s)\n\n"
                f"Applied by AI Review Agent using Aider + Amazon Bedrock Nova Pro.\n"
                f"Files fixed: {files_fixed}{skipped_note}{warning_note}\n"
                f"Original PR: {state.pr_url}"
            )
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=repo_path, check=True, capture_output=True,
            )
        else:
            log.info("aider_llm_fix_no_llm_changes", reason="no fixable findings or Aider made no edits")

        # ------------------------------------------------------------------
        # STEP F: Local CI Loop — ruff + sqlfluff on whole repo, up to 3x
        # ------------------------------------------------------------------
        ci_passed = False
        for ci_attempt in range(1, MAX_CI_LINT_ATTEMPTS + 1):
            log.info("local_ci_check", attempt=ci_attempt)
            
            # --- Global Native Auto-Fixes ---
            subprocess.run(["ruff", "format", "src/"], cwd=repo_path, capture_output=True)
            subprocess.run(["ruff", "check", "--fix", "--unsafe-fixes", "src/"], cwd=repo_path, capture_output=True)
            if os.path.exists(os.path.join(repo_path, "models")):
                subprocess.run(["sqlfluff", "fix", "models/", "--dialect", "ansi", "--force"], cwd=repo_path, capture_output=True)
            
            # Commit any native auto-fixes immediately before checking if CI passes
            subprocess.run(["git", "add", "-A"], cwd=repo_path, capture_output=True)
            diff_format = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo_path, capture_output=True)
            if diff_format.returncode != 0:
                subprocess.run(
                    ["git", "commit", "-m", f"fix(ci): native auto-format attempt {ci_attempt}"],
                    cwd=repo_path, check=False, capture_output=True,
                )

            # Re-check what remains
            ruff_result = subprocess.run(
                ["ruff", "check", "src/"], cwd=repo_path, capture_output=True, text=True
            )
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
                # Extract failing files dynamically from stdout
                import re
                failing_files = set()
                if not ruff_ok:
                    matches = re.findall(r"(?m)^([a-zA-Z0-9_./-]+):\d+:\d+:", ruff_result.stdout)
                    failing_files.update(matches)
                if not sqlfluff_ok:
                    matches = re.findall(r"([a-zA-Z0-9_./-]+\.sql)", sqlfluff_result.stdout, re.IGNORECASE)
                    failing_files.update(matches)
                failing_files = failing_files if failing_files else set(files_fixed)

                for fp in failing_files:
                    if not os.path.exists(os.path.join(repo_path, fp)):
                        continue
                        
                    ci_prompt = build_ci_lint_prompt(agent_branch, ci_errors, fp)
                    aider_ci_cmd = [
                        "aider", "--yes", "--no-gui", "--no-show-release-notes",
                        "--no-show-model-warnings", "--no-check-update",
                        "--no-auto-commits", "--no-stream", "--no-git",
                        "--map-tokens", "0", "--edit-format", "whole",
                        "--lint-cmd", "python: ruff check", "--auto-lint",
                        "--model", "bedrock/amazon.nova-pro-v1:0",
                        "--message", ci_prompt, fp,
                    ]
                    subprocess.run(
                        aider_ci_cmd, cwd=repo_path, capture_output=True,
                        text=True, timeout=150, stdin=subprocess.DEVNULL,
                    )

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
        # STEP G: Smart push — only push if something actually changed
        # Compare local HEAD to remote HEAD to avoid empty pushes
        # ------------------------------------------------------------------
        local_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_path, capture_output=True, text=True
        ).stdout.strip()
        remote_hash_result = subprocess.run(
            ["git", "rev-parse", f"origin/{agent_branch}"],
            cwd=repo_path, capture_output=True, text=True
        )
        remote_hash = remote_hash_result.stdout.strip() if remote_hash_result.returncode == 0 else ""

        dev_hash_result = subprocess.run(
            ["git", "rev-parse", f"origin/{developer_branch}"],
            cwd=repo_path, capture_output=True, text=True
        )
        dev_hash = dev_hash_result.stdout.strip() if dev_hash_result.returncode == 0 else ""

        if local_hash == remote_hash:
            if local_hash != dev_hash and dev_hash != "":
                log.info("aider_llm_fix_already_pushed", reason="fixes already exist on remote agent branch")
                return {
                    "aider_fix_applied": True,
                    "aider_fix_summary": "Agent fixes from a previous run are already up-to-date on the remote branch.",
                    "agent_branch": agent_branch,
                }
            else:
                log.info("aider_llm_fix_no_net_changes", reason="local HEAD matches remote, nothing to push")
                return {
                    "aider_fix_applied": False,
                    "aider_fix_summary": "CI passed with no changes needed. Branch is already clean.",
                    "agent_branch": agent_branch,
                }

        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
             "push", "origin", agent_branch],
            cwd=repo_path, check=True, capture_output=True,
        )
        log.info("agent_branch_pushed", branch=agent_branch, ci_passed=ci_passed)

        had_llm_fixes = bool(files_fixed)
        if had_llm_fixes:
            summary = (
                f"Fixed {len(files_fixed)} file(s) from LLM review on branch `{agent_branch}`."
                + (f" {len(files_kept_with_warnings)} file(s) kept with lint warnings." if files_kept_with_warnings else "")
                + (f" Discarded {len(files_skipped)} file(s) as unparseable." if files_skipped else "")
                + (" Local CI passed." if ci_passed else f" Local CI still failing after {MAX_CI_LINT_ATTEMPTS} attempts — PR raised anyway.")
            )
        else:
            summary = (
                f"0 high-confidence LLM findings. CI/lint issues were found and fixed on branch `{agent_branch}`."
                + (" Local CI passed after fixes." if ci_passed else f" Local CI still failing after {MAX_CI_LINT_ATTEMPTS} attempts — PR raised anyway.")
            )

        log.info("aider_llm_fix_committed", branch=agent_branch, fixed=files_fixed, ci_only=not had_llm_fixes)
        return {
            "aider_fix_applied": had_llm_fixes,
            "aider_fix_summary": summary,
            "agent_branch": agent_branch,
        }

    except subprocess.TimeoutExpired:
        log.error("aider_llm_fix_timeout")
        return {"aider_fix_applied": False, "aider_fix_summary": "Aider timed out.", "agent_branch": agent_branch}
    except Exception as e:
        log.error("aider_llm_fix_error", error=str(e))
        return {"aider_fix_applied": False, "aider_fix_summary": f"Aider error: {e}", "agent_branch": agent_branch}
