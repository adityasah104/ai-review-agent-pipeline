import textwrap
import structlog
from src.agents.state import PRReviewState
from src.agents.utils.llm import build_file_context, call_bedrock_review

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """Reviews code for performance issues using Bedrock Nova Pro."""
    log.info("performance_review_start")

    if not state.file_contents:
        return {"findings": []}

    files_text = build_file_context(state)

    prompt = textwrap.dedent(f"""\
        You are a ruthless performance engineering expert reviewing Python and SQL code.

        CRITICAL RULES (violating any of these makes your review invalid):
        1. DO NOT invent or hallucinate issues. If the code is perfectly fine, return an empty
           array []. You are NOT required to find a problem. Zero findings is a completely
           normal, acceptable, and often correct result.
        2. DO NOT change or complain about business logic. If a developer explicitly selects
           specific columns (e.g., SELECT col1, col2), do not suggest changing it, renaming
           it, reordering it, or adding/removing columns from it.
        3. In SQL, ONLY flag SELECT * as a bad practice regarding column selection. Never
           complain about explicit column selections — an explicit column list is always
           correct, no matter how it's styled or ordered.
        4. If a piece of code is stylized a certain way but is functionally correct and not a
           security risk, leave it alone. Do not report subjective style preferences,
           nitpicks, or theoretical micro-optimizations.
        5. YOU MUST ONLY CHECK FOR THE ISSUES IN THE STRICT CHECKLIST BELOW. Do NOT use your general knowledge.

        Review the following code for SEVERE PERFORMANCE issues only.
        You MUST ONLY report actionable bottlenecks that require an immediate code change.
        DO NOT report micro-optimizations, theoretical scaling concerns, or minor nitpicks.

        STRICT CHECKLIST - Look ONLY for these exact issues:
        N+1 query patterns in Python (loops that execute database queries)
        Inefficient JOINs or missing partition/cluster keys in dbt models
        SELECT * in SQL (fetches unnecessary columns)
        Large result sets loaded entirely into memory in Python
        Blocking I/O (e.g. synchronous requests, subprocess, or file operations) inside async functions
        Unbounded caching or memory growth from module-level mutable state
        dbt models missing incremental materializations for large tables
        Repeated expensive function calls inside loops
        SQL DISTINCT or ORDER BY on large unsorted datasets without purpose

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
        severity: "critical" or "major" (DO NOT return "minor")
        category: "performance"
        description: string (clear explanation of the severe bottleneck, explicitly naming the specific pattern instance e.g., quoting the loop variable and query call)
        suggestion: string
        confidence: float (0.0 to 1.0)
          0.9-1.0 = pattern is unambiguous and the exact line is quoted
          0.5-0.7 = pattern matches but context is incomplete
          below 0.5 = do not include the finding at all

        Return ONLY the JSON array, no other text. If no issues found, return [].
    """)

    try:
        findings = call_bedrock_review(prompt)
        log.info("performance_review_done", findings_count=len(findings))
        return {"findings": findings}
    except Exception as e:
        log.error("performance_review_error", error=str(e))
        return {"findings": []}