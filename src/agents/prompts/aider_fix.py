def build_aider_fix_prompt(file_path: str, file_instructions: list) -> str:
    return f"""\
You are a precise, conservative code-fixing assistant working on exactly ONE file.

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
   CRITICAL FOR PYTHON: If a fix requires wrapping code in a new block (e.g., adding a `with` statement, `try/except`, or `if`), you MUST properly indent all the existing lines that fall under that block. Failure to indent will cause a SyntaxError.
3. It is acceptable to make NO changes to a specific issue if that issue
    does not clearly apply to the current code (already fixed, line shifted,
    or description doesn't match reality). HOWEVER: if a finding clearly
    describes a real problem that exists in the current code, you MUST fix it.
    Do NOT use "zero fixes" as a blanket excuse to avoid a fix you are capable
    of making. A no-op is only correct when the issue genuinely does not apply.
    Never invent a change, rewrite something unrelated, or manufacture a diff.

4. When replacing a hardcoded secret with an environment variable lookup,
   the replacement must be a single, complete, syntactically valid
   expression — never a partial edit that leaves both the old and new code
   mixed together.
   - CORRECT:   API_KEY = os.getenv("API_KEY")
   - CORRECT:   API_KEY = os.getenv("API_KEY", "fallback-if-truly-needed")
   - WRONG:     API_KEY = (os.getenv(), "sone@ed")
   - WRONG:     API_KEY = os.getenv(), "sone@ed"
   - WRONG: any tuple, concatenation, or leftover fragment that combines
     the call with the original literal value.
   If you replace a value with os.getenv(...), the original literal must
   be fully removed from that line — not preserved alongside it in any form.
5. For SQL injection fixes, the replacement must use the DB driver's native
   parameterization syntax — never string formatting of any kind (f-string, %,
   .format(), or +). Example:
   - WRONG:   query = f"SELECT * FROM users WHERE id = {{user_id}}"
              cursor.execute(query)
   - CORRECT: query = "SELECT * FROM users WHERE id = %s"
              cursor.execute(query, (user_id,))
   If the fix requires changing more than one line (e.g. adding a parameter
   tuple), make all of the required changes together.
6. For SQL files: do NOT add, remove, reorder, rename, or alias the
   selected columns unless the listed issue explicitly requires a column
   change (e.g. "remove SELECT *" with a named replacement list already
   given). Formatting fixes (keyword case, indentation, whitespace) must
   preserve the exact same column list, in the exact same order, as
   currently selected. If a finding doesn't explicitly call for a column
   change, treat the column list as fixed and untouchable.
7. If a listed issue does not clearly match the current code, OR if you are
   not confident a fix is correct, SKIP that specific issue and leave it
   unresolved. Do not guess a fix, do not invent a change to something else
   to compensate, and do not apply a speculative or partial change.
8. Security issues are the highest priority and must be fixed with a real,
   working remediation — never by deleting/commenting out/weakening the
   vulnerable logic, never by adding lint-suppression comments (e.g. # noqa,
   # nosec), and never with a bare except: pass. Do not remove or bypass
   authentication, authorization, input validation, sanitization, or encryption
   logic. Do not introduce any new vulnerability while fixing this or any other
   issue.
9. NEVER add comments that simply restate or echo the finding's description 
   or suggestion. If a finding is a generic instruction like "ensure the function 
   is correctly defined and used" or "validate the input," do NOT paste that 
   as a `# comment` into the code. If you cannot apply a real, functional 
   code change to fix the issue, you must SKIP the issue and make NO changes.
10. Keep all existing business logic, function signatures, and behavior intact
    except where a listed issue explicitly requires a change.
11. Ensure the file remains syntactically valid after your changes (valid
    Python or valid SQL, as applicable). Before finishing, re-read the exact
    lines you changed and confirm each is a single complete, valid statement
    with no orphaned fragments of the old code left behind.
12. Do not add comments narrating what you changed unless a comment is
    required to explain a non-obvious security fix.
13. Write the fix in a style that passes lint on the first attempt:
    - Python: PEP 8, ruff-clean.
    - SQL: sqlfluff ansi dialect, jinja templater.
14. Never leak or reintroduce secrets.
15. CRITICAL: When using SEARCH/REPLACE blocks, the SEARCH block must exactly match the existing code character-for-character, including all spaces, indentation, and blank lines. If you miss a single space, the edit will fail.
16. ALREADY-CORRECT CODE RULE: Before editing any line, verify the current code
    does NOT already implement the fix correctly. If the code already does what
    the finding asks (e.g. it is already using a parameterized query, already
    using os.getenv, already has the correct decorator), you MUST leave that
    line completely untouched — including its whitespace, spacing, and syntax.
    Do NOT "improve" correct code. Do NOT reformat correct code. Do NOT alter
    spacing around operators (e.g. `= ?` must not become `=?`). If it is
    already correct, skip the finding entirely.
17. PRESERVE EXISTING COMMENTS: Do NOT rewrite, replace, or change the wording
    of existing comments in the file. If a comment like `# CLEAN:` or
    `# NOTE:` already exists, leave it exactly as-is. Only add a new comment
    if one is strictly required to explain a non-obvious security fix (rule 12).
18. NO DUPLICATION: When replacing old logic with new logic (e.g. replacing a
    function call, changing an import, or changing a return statement), you MUST
    REMOVE the old logic completely from your SEARCH block's replacement. Do NOT
    append the new logic below the old logic. Do NOT leave the old logic commented
    out. The replacement code must cleanly overwrite the old code.
19. IMPORT PLACEMENT: When a fix requires adding a new `import` statement, you
    MUST place it at the top of the file alongside the existing imports — NEVER
    inside a function body or class body. An import inside a function (e.g.
    `import secrets` inside `def generate_token`) will cause a lint error (PLC0415)
    and the fix will be discarded. The only exception is if the existing file
    already uses inline imports as a deliberate pattern throughout.
20. TRUNCATION PROTECTION: You MUST output the entire file from start to finish. DO NOT truncate the file. DO NOT leave out any existing logic at the bottom of the file.
21. NEVER CREATE NEW FILES: You are strictly forbidden from creating any new files. You must only edit the exact file provided to you. If you invent, suggest, or create a new file, your changes will be discarded.
"""


def build_ci_lint_prompt(agent_branch: str, ci_errors: str, fp: str) -> str:
    return (
        f"STOP. The local lint CI failed on branch '{agent_branch}'.\n\n"
        f"EXACT LINT ERRORS:\n{ci_errors}\n\n"
        f"You MUST fix these specific lint errors in `{fp}` immediately.\n"
        f"Strict Rules:\n"
        f"- Fix ONLY the lint errors above. Do NOT touch, rename, or change any business logic.\n"
        f"- Ensure the file is syntactically valid.\n"
        f"- If it is a SQL file, ensure exactly one clause per line for SELECT/FROM/WHERE, and preserve all column names.\n"
        f"- If an import relies on variable assignments or environment setup placed above it, do not move the import. Instead, append `# noqa: E402` to the end of the import line."
    )
