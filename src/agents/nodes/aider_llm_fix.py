import re
import subprocess
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings
from src.azure_client.auth import get_azure_devops_token

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


async def run(state: PRReviewState) -> dict:
    """
    Phase 2: Creates agent/<developer-branch> in ADO, checks it out locally,
    applies Aider fixes there, runs local ruff+sqlfluff CI up to 3 times,
    then pushes. Developer branch is NEVER touched.
    """
    # Use PR-Agent's refined findings if available, otherwise fall back to raw findings
    active_findings = state.refined_findings if state.refined_findings else state.findings
    log.info("aider_llm_fix_start", findings_count=len(active_findings))

    # Filter: auto-fix minor, major, and critical that meet confidence threshold
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

    # Get unique file paths that have fixable findings
    files_to_fix = list(set(
        f["file_path"].lstrip("/") for f in fixable_findings
        if f.get("file_path")
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
        subprocess.run(
            ["git", "checkout", agent_branch],
            cwd=repo_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
             "pull", "origin", agent_branch, "--rebase"],
            cwd=repo_path, check=False, capture_output=True,
        )

        # ---------------------------------------------------------
        # STEP D: Process ONE file at a time on the agent branch
        # Each file gets its own Aider call + validation gate.
        # If one file breaks, only that file is discarded —
        # the rest are still committed safely.
        # ---------------------------------------------------------
        files_fixed = []
        files_skipped = []
        files_kept_with_warnings = []

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

            base_file_prompt = f"""You are a precise, conservative code-fixing assistant working on exactly ONE file.                        
                                                                                                                                                 
    First, read the current content of `{file_path}` carefully before changing anything.                                                         
    Do not rely on assumed line numbers below if the file content has shifted.                                                                   
                                                                                                                                                 
    Fix ONLY the following reviewer-identified issues in `{file_path}`:                                                                          
                                                                                                                                                 
    {chr(10).join(file_instructions)}                                                                                                            
                                                                                                                                                 
    Strict rules — follow all of them:                                                                                                           
    1. Make ONLY the minimal change needed to resolve each listed issue. Do not                                                                  
       refactor, rename, reformat, reorganize, or "clean up" any code that isn't                                                                 
       part of a listed issue.                                                                                                                   
    2. DO NOT change business logic. This is critical.
       - Do NOT change database table names, view names, or schemas.
       - NEVER change the target of a dbt `{{{{ ref('...') }}}}` or `{{{{ source('...') }}}}`. If the code says `ref('orders')`, LEAVE IT AS `orders`.
       - DO NOT change SQL table aliases (e.g. changing `final as o` to `final as f`). Leave aliases exactly as the developer wrote them.
    3. It is a completely acceptable outcome to make NO changes at all. If none                                                                  
       of the listed issues clearly apply to the current code, leave the file untouched.                                                                     
    4. When replacing a hardcoded secret with an environment variable lookup,                                                                    
       the replacement must be a single, complete, syntactically valid expression.
    5. For SQL files: do NOT add, remove, reorder, rename, or alias the                                                                          
       selected columns unless the listed issue explicitly requires it.                                                                                   
    6. If a listed issue does not clearly match the current code, SKIP that specific issue.
    7. Security issues are the highest priority and must be fixed with a real,                                                                   
       working remediation.                                                                                                    
    8. NEVER add comments that simply restate or echo the finding's description.
    9. Keep all existing business logic, function signatures, and behavior intact.                                                                               
    10. Ensure the file remains syntactically valid after your changes.                                                                                 
    11. Write the fix in a style that passes lint on the first attempt (PEP 8 / sqlfluff ansi).                                                                          
    12. Never leak or reintroduce secrets.
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
                    "--edit-format", "diff",
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
                log.info(
                    "aider_llm_fix_file_output",
                    file=file_path, attempt=attempt, returncode=result.returncode,
                )

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
                    files_fixed.append(file_path)
                    fixed = True
                    log.info("aider_llm_fix_file_passed", file=file_path, attempt=attempt)
                    break

                feedback = (
                    f"Ruff codes newly introduced: {sorted(introduced_ruff)}\n"
                    f"Sqlfluff codes newly introduced: {sorted(introduced_sqlfluff)}"
                )
                log.warning(
                    "aider_llm_fix_file_attempt_failed",
                    file=file_path, attempt=attempt,
                    introduced_ruff=sorted(introduced_ruff),
                    introduced_sqlfluff=sorted(introduced_sqlfluff),
                )

            if not fixed:
                has_major_critical = any(
                    str(f.get("severity", "")).lower() in ("major", "critical")
                    for f in file_findings
                )
                if has_major_critical and _is_syntactically_valid(repo_path, file_path):
                    files_fixed.append(file_path)
                    files_kept_with_warnings.append(file_path)
                    log.warning(
                        "aider_llm_fix_file_kept_with_lint_warnings",
                        file=file_path, remaining_issues=feedback,
                    )
                else:
                    subprocess.run(["git", "checkout", "--", file_path], cwd=repo_path, capture_output=True)
                    subprocess.run(["git", "clean", "-fd", "--", file_path], cwd=repo_path, capture_output=True)
                    files_skipped.append(file_path)
                    log.error(
                        "aider_llm_fix_file_discarded_unparseable",
                        file=file_path, last_feedback=feedback,
                    )

        # ------------------------------------------------------------------
        # STEP E: Commit to the AGENT branch (never git add -A)
        # ------------------------------------------------------------------
        if files_fixed:
            subprocess.run(["git", "add", "--", *files_fixed], cwd=repo_path, check=True, capture_output=True)

        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_path, capture_output=True,
        )

        if diff_result.returncode == 0:
            summary = "Aider ran but found no changes to apply."
            log.info("aider_llm_fix_no_changes")
            return {"aider_fix_applied": False, "aider_fix_summary": summary, "agent_branch": agent_branch}

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

        # ------------------------------------------------------------------
        # STEP F: Local CI Loop — ruff + sqlfluff on whole repo, up to 3x
        # ------------------------------------------------------------------
        ci_passed = False
        for ci_attempt in range(1, MAX_CI_LINT_ATTEMPTS + 1):
            log.info("local_ci_check", attempt=ci_attempt)
            ruff_result = subprocess.run(
                ["ruff", "check", "src/"], cwd=repo_path, capture_output=True, text=True
            )
            sqlfluff_result = subprocess.run(
                ["sqlfluff", "lint", "models/", "--dialect", "ansi", "--format", "human"],
                cwd=repo_path, capture_output=True, text=True,
            )
            pytest_result = subprocess.run(
                ["pytest"], cwd=repo_path, capture_output=True, text=True
            )
            
            ruff_ok = ruff_result.returncode == 0
            sqlfluff_ok = sqlfluff_result.returncode == 0
            # pytest returns 5 if no tests are collected, which we consider a pass
            pytest_ok = pytest_result.returncode in (0, 5)
            
            log.info("local_ci_result", attempt=ci_attempt, ruff_ok=ruff_ok, sqlfluff_ok=sqlfluff_ok, pytest_ok=pytest_ok)

            if ruff_ok and sqlfluff_ok and pytest_ok:
                ci_passed = True
                log.info("local_ci_passed", attempt=ci_attempt)
                break

            if ci_attempt < MAX_CI_LINT_ATTEMPTS:
                ci_errors = ""
                if not ruff_ok:
                    ci_errors += f"=== Ruff errors ===\n{ruff_result.stdout}\n"
                if not sqlfluff_ok:
                    ci_errors += f"=== SQLFluff errors ===\n{sqlfluff_result.stdout}\n"
                if not pytest_ok:
                    ci_errors += f"=== Pytest errors ===\n{pytest_result.stdout}\n{pytest_result.stderr}\n"
                log.warning("local_ci_failed_retrying", attempt=ci_attempt)

                for fp in files_fixed:
                    ci_prompt = (
                            f"STOP. Your previous fix broke the build. The local lint CI failed on branch '{agent_branch}'.\n\n"
                            f"EXACT LINT ERRORS:\n{ci_errors}\n\n"
                            f"You MUST fix these specific lint errors in `{fp}` immediately.\n"
                            f"Strict Rules:\n"
                            f"- Fix ONLY the lint errors above. Do NOT touch, rename, or change any business logic.\n"
                            f"- DO NOT change database table names, view names, schemas, or `ref()` / `source()` targets.\n"
                            f"- DO NOT change SQL table aliases (e.g. leave `final as o` alone) unless the lint error explicitly demands it.\n"
                            f"- Ensure the file is syntactically valid.\n"
                            f"- If it is a SQL file, ensure exactly one clause per line for SELECT/FROM/WHERE, and preserve all column names."   
                        )
                    aider_ci_cmd = [
                        "aider", "--yes", "--no-gui", "--no-show-release-notes",
                        "--no-show-model-warnings", "--no-check-update",
                        "--no-auto-commits", "--no-stream", "--no-git",
                        "--map-tokens", "0", "--edit-format", "diff",
                        "--lint-cmd", "python: ruff check", "--auto-lint",
                        "--model", "bedrock/amazon.nova-pro-v1:0",
                        "--message", ci_prompt, fp,
                    ]
                    subprocess.run(
                        aider_ci_cmd, cwd=repo_path, capture_output=True,
                        text=True, timeout=150, stdin=subprocess.DEVNULL,
                    )
                    subprocess.run(["ruff", "format", fp], cwd=repo_path, capture_output=True)
                    subprocess.run(["ruff", "check", "--fix", "--unsafe-fixes", fp], cwd=repo_path, capture_output=True)

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
        # STEP G: Push ONLY the agent branch to origin
        # ------------------------------------------------------------------
        subprocess.run(
            ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}",
             "push", "origin", agent_branch],
            cwd=repo_path, check=True, capture_output=True,
        )
        log.info("agent_branch_pushed", branch=agent_branch, ci_passed=ci_passed)

        summary = (
            f"Fixed {len(files_fixed)} file(s) on branch `{agent_branch}`."
            + (f" {len(files_kept_with_warnings)} file(s) kept with lint warnings." if files_kept_with_warnings else "")
            + (f" Discarded {len(files_skipped)} file(s) as unparseable." if files_skipped else "")
            + (" Local CI passed." if ci_passed else f" Local CI still failing after {MAX_CI_LINT_ATTEMPTS} attempts — PR raised anyway.")
        )
        log.info("aider_llm_fix_committed", branch=agent_branch, fixed=files_fixed)
        return {"aider_fix_applied": True, "aider_fix_summary": summary, "agent_branch": agent_branch}

    except subprocess.TimeoutExpired:
        log.error("aider_llm_fix_timeout")
        return {"aider_fix_applied": False, "aider_fix_summary": "Aider timed out.", "agent_branch": agent_branch}
    except Exception as e:
        log.error("aider_llm_fix_error", error=str(e))
        return {"aider_fix_applied": False, "aider_fix_summary": f"Aider error: {e}", "agent_branch": agent_branch}
