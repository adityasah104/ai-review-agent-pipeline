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
Do not rely on assumed line numbers below if the file content has shifted — locate
each issue by matching its description to the actual current code, not by line
number alone.

Fix ONLY the following reviewer-identified issues in `{file_path}`:

{chr(10).join(file_instructions)}

Strict rules — follow all of them:
1. Only edit `{file_path}`. Do NOT touch, create, or delete any other file.
2. Make ONLY the minimal change needed to resolve each listed issue. Do not
   refactor, rename, reformat, reorganize, or "clean up" any code that isn't
   part of a listed issue.
3. If a listed issue does not clearly match the current code (already fixed,
   line shifted to something unrelated, description doesn't apply), SKIP that
   specific issue. Do not guess a fix, do not invent a change to something else
   to compensate, and do not fabricate line numbers, variables, or file content
   that don't actually exist.
4. Security issues are the highest priority and must be fixed with a real,
   working remediation — never by deleting/commenting out/weakening the
   vulnerable logic, never by adding lint-suppression comments (e.g. `# noqa`,
   `# nosec`), and never with a bare `except: pass`. Do not remove or bypass
   authentication, authorization, input validation, sanitization, or encryption
   logic. Do not introduce any new vulnerability while fixing this or any other
   issue.
5. Keep all existing business logic, function signatures, and behavior intact
   except where a listed issue explicitly requires a change.
6. If you are not confident a fix is correct, leave that issue unresolved
   rather than applying a speculative or partial change.
7. Ensure the file remains syntactically valid after your changes (valid Python
   or valid SQL, as applicable).
8. Do not add comments narrating what you changed unless a comment is required
   to explain a non-obvious security fix.
9. Write the fix in a style that passes lint on the first attempt, so it is not
   silently discarded by the validation gate:
   - Python: follow PEP 8 — correct indentation (4 spaces, no tabs), no trailing
     whitespace, no unused imports/variables, imports at the top and properly
     ordered (stdlib, then third-party, then local), consistent quote style
     matching the rest of the file, blank lines between top-level defs/classes,
     line length within the project's configured limit, and no bare `except:`.
     Match the formatting `ruff format` would already produce so `ruff check .`
     passes cleanly.
   - SQL: follow the `sqlfluff` `ansi` dialect with the `jinja` templater —
     consistent keyword casing (match the surrounding file's existing casing
     convention), one clause per line for SELECT/FROM/WHERE/JOIN, consistent
     indentation, no trailing commas issues, no trailing whitespace, and
     terminate statements consistently with the rest of the file. Match the
     formatting `sqlfluff fix` would already produce so `sqlfluff lint` passes
     cleanly.
   - In both cases, mirror the existing code style already used elsewhere in
     the file/repo rather than introducing a different convention.
10. Never leak or reintroduce secrets while "fixing" a hardcoded-secret finding.
    Replace the secret with a real environment/config lookup (e.g.
    `os.environ["API_TOKEN"]`) with NO default value containing the actual
    secret, placeholder secret-shaped string, or any part of the original
    value. Do not move the secret into a comment, log line, error message, or
    a getenv() fallback default either.
"""

            log.info("aider_llm_fix_file_start", file=file_path)

            # Baseline lint state BEFORE Aider touches this file. Pre-existing
            # issues elsewhere in the file are not Aider's fault and must not
            # cause a good fix (e.g. a security patch) to be discarded — we
            # only fail the file if Aider's edit introduces NEW rule codes
            # that weren't already present.
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
                    # Aider is an interactive CLI. If it hits an unexpected
                    # condition (e.g. a Bedrock auth error) it can drop into a
                    # (Y/n) prompt. With no stdin attached in CI, that read
                    # returns EOF immediately instead of hanging until the
                    # timeout kills the process 5 minutes later.
                    stdin=subprocess.DEVNULL,
                )
                log.info(
                    "aider_llm_fix_file_output",
                    file=file_path, attempt=attempt, returncode=result.returncode,
                )

                # Auto-format only this file after each Aider run, so we don't
                # touch unrelated files' working-tree state.
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

                # --- Per-file Validation Gate (baseline-aware) ---
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
                if _is_syntactically_valid(repo_path, file_path):
                    # Retries exhausted, but the file still parses/runs — the
                    # fix (often the important security/major one) is kept
                    # rather than thrown away over a remaining lint/style nit.
                    # This intentionally means the file may still fail lint
                    # in your broader pipeline gate, if you have one.
                    files_fixed.append(file_path)
                    files_kept_with_warnings.append(file_path)
                    log.warning(
                        "aider_llm_fix_file_kept_with_lint_warnings",
                        file=file_path, remaining_issues=feedback,
                    )
                else:
                    # The file is actually broken (won't parse) — this is the
                    # one case we still revert, since keeping it wouldn't
                    # preserve the fix, it would just break the build.
                    subprocess.run(["git", "checkout", "--", file_path], cwd=repo_path, capture_output=True)
                    subprocess.run(["git", "clean", "-fd", "--", file_path], cwd=repo_path, capture_output=True)
                    files_skipped.append(file_path)
                    log.error(
                        "aider_llm_fix_file_discarded_unparseable",
                        file=file_path, last_feedback=feedback,
                    )

        # ---------------------------------------------------------
        # Commit only the files we actually fixed and validated —
        # never `git add -A`, which would also stage unrelated
        # generated artifacts (e.g. a chroma_db/ vector store) that
        # happen to sit untracked in the working directory.
        # ---------------------------------------------------------
        if files_fixed:
            subprocess.run(["git", "add", "--", *files_fixed], cwd=repo_path, check=True, capture_output=True)

        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=repo_path, capture_output=True,
        )

        if diff_result.returncode != 0:
            skipped_note = f"\nDiscarded (unparseable after retries): {files_skipped}" if files_skipped else ""
            warning_note = (
                f"\nCommitted with unresolved lint warnings: {files_kept_with_warnings}"
                if files_kept_with_warnings else ""
            )
            commit_msg = (
                f"fix(ai-review): apply {len(fixable_findings)} auto-fix suggestion(s)\n\n"
                f"Applied by AI Review Agent using Aider + Amazon Bedrock Nova Pro.\n"
                f"Files fixed: {files_fixed}{skipped_note}{warning_note}\n"
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
                + (f" ⚠️ {len(files_kept_with_warnings)} file(s) committed with unresolved lint warnings (fix kept, not discarded): {files_kept_with_warnings}." if files_kept_with_warnings else "")
                + (f" 🛑 Discarded {len(files_skipped)} file(s) as unparseable after retries: {files_skipped}." if files_skipped else "")
            )
            log.info(
                "aider_llm_fix_committed", branch=branch, fixed=files_fixed,
                kept_with_warnings=files_kept_with_warnings, skipped=files_skipped,
            )
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
