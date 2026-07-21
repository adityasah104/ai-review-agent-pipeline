import textwrap
import structlog
from src.agents.state import PRReviewState
from src.agents.utils.llm import build_file_context, call_bedrock_review

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """
    Reviews Python and SQL code quality using Bedrock Nova Pro.
    Returns structured findings as a list.
    """
    log.info("code_quality_review_start")

    if not state.file_contents:
        return {"findings": []}

    files_text = build_file_context(state)

    rag_text = "\n".join(state.rag_context[:4]) if state.rag_context else "No guidelines available."

    prompt = textwrap.dedent(f"""\
        You are a ruthless, senior code reviewer specializing in Python and dbt/SQL.

        Relevant coding guidelines from our internal standards:
        {rag_text}

        CRITICAL RULES (violating any of these makes your review invalid):
        1. DO NOT invent or hallucinate issues. If the code is perfectly fine, return an empty
           array []. You are NOT required to find a problem. Zero findings is a completely
           normal, acceptable, and often correct result.
        2. DO NOT change or complain about business logic. If a developer explicitly selects
           specific columns (e.g., SELECT col1, col2), do not suggest changing it, renaming
           it, reordering it, or adding/removing columns from it. 
        3. In SQL, never complain about explicit column selections — an explicit column list is always
           correct, no matter how it's styled or ordered.
        4. If a piece of code is stylized a certain way but is functionally correct and not a
           security risk, leave it alone unless it explicitly matches a minor style issue in the checklist. Do not report subjective style preferences,
           nitpicks, or "could be cleaner" suggestions.
        5. YOU MUST ONLY CHECK FOR THE ISSUES IN THE STRICT CHECKLIST BELOW. Do NOT use your general knowledge.

        Review the following code changes for CODE QUALITY, LOGIC, and STYLE issues.
        You MUST ONLY report actionable bugs or explicit style/quality issues matching the checklist.

        STRICT CHECKLIST - Look ONLY for these exact issues:
        - Severe logic errors, unhandled exceptions, or broken functionality
        - dbt model naming convention violations that break DAG execution
        - Missing {{{{ ref() }}}} or {{{{ source() }}}} macro usage in dbt SQL
        - Missing context manager (with block) on file open() or similar resources
        - Mutable default arguments in function definitions (e.g. def foo(x=[]))
        - Bare print() statements (should use logging instead)
        - Missing return type annotations on new functions

        Here is the code context. You are provided with the changed lines (diff) or the full file if no diff is available:
        {files_text}

        IMPORTANT: Only report issues introduced in the changed lines (if a diff is provided).
        Do NOT flag pre-existing issues in unchanged context lines.
        If an issue does not absolutely require a code change, IGNORE IT.
        Before returning a finding, double-check it does not violate any of the CRITICAL RULES above.
        NEVER emit generic, unactionable advice like "Ensure the function is correctly defined and used". If a bug isn't explicitly identifiable, SKIP IT.
        It is far better to return [] than to report a false or unnecessary finding.

        Return your findings as a JSON array. Each finding must have:
        file_path: string
        line_number: integer — the exact line number from the file. If using a diff, infer the line number from the @@ headers.
        severity: "minor", "major", or "critical"
        category: "code_quality"
        description: string (clear explanation of the issue)
        suggestion: string (exactly how to fix it)
        confidence: float (0.0 to 1.0)
          0.9-1.0 = pattern is unambiguous and the exact line is quoted
          0.5-0.7 = pattern matches but context is incomplete
          below 0.5 = do not include the finding at all

        Return ONLY the JSON array, no other text. If no issues found, return [].
    """)

    try:
        findings = call_bedrock_review(prompt)
        log.info("code_quality_review_done", findings_count=len(findings))
        return {"findings": findings}
    except Exception as e:
        log.error("code_quality_review_error", error=str(e))
        return {"findings": []}