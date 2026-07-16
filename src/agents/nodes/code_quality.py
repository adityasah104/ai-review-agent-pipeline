import json
import boto3
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings

log = structlog.get_logger()


def _call_bedrock(prompt: str) -> str:
    """Calls Amazon Bedrock Nova Pro and returns response text."""
    client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        "inferenceConfig": {
            "maxTokens": 5120,
            "temperature": 0,
        },
    }
    response = client.invoke_model(
        modelId=settings.BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )

    result = json.loads(response["body"].read())
    return result["output"]["message"]["content"][0]["text"]


async def run(state: PRReviewState) -> dict:
    """
    Reviews Python and SQL code quality using Bedrock Nova Pro.
    Returns structured findings as a list.
    """
    log.info("code_quality_review_start")

    if not state.file_contents:
        return {"findings": []}

    # Build file text with explicit line numbers
    files_text = ""
    for path, content in state.file_contents.items():
        # Add line numbers to full content
        lines = content.split('\n')
        numbered_lines = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]
        numbered_content = "\n".join(numbered_lines)
        
        diff = state.file_diffs.get(path, "No diff available.")
        
        files_text += f"\n\n### File: {path}\n"
        files_text += f"--- FULL FILE WITH LINE NUMBERS ---\n```\n{numbered_content[:4000]}\n```\n"
        files_text += f"--- CHANGED LINES (diff) ---\n```diff\n{diff[:2000]}\n```\n"

    rag_text = "\n".join(state.rag_context[:4]) if state.rag_context else "No guidelines available."

    prompt = f"""You are a ruthless, senior code reviewer specializing in Python and dbt/SQL.

Relevant coding guidelines from our internal standards:
{rag_text}

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
   nitpicks, or "could be cleaner" suggestions.

Review the following code changes for SEVERE CODE QUALITY and LOGIC issues only.
You MUST ONLY report actionable bugs that require an immediate code change.
DO NOT report nitpicks (e.g., missing docstrings, PEP 8 style issues, minor naming conventions, or subjective refactoring suggestions).

Look for:
Severe logic errors, unhandled exceptions, or broken functionality
Hardcoded values that should be constants or environment variables
dbt model naming convention violations that break DAG execution
Missing {{ ref() }} or {{ source() }} macro usage in dbt SQL
SELECT * usage in SQL models that causes schema drift

Here is the code context. You are provided with the full file (with line numbers on the left) and the git diff:
{files_text}

IMPORTANT: Only report issues introduced in the changed lines (shown in the diff).
Do NOT flag pre-existing issues in unchanged context lines.
If an issue does not absolutely require a code change, IGNORE IT.
Before returning a finding, double-check it does not violate any of the CRITICAL RULES above.
NEVER emit generic, unactionable advice like "Ensure the function is correctly defined and used". If a bug isn't explicitly identifiable, SKIP IT.
It is far better to return [] than to report a false or unnecessary finding.

Return your findings as a JSON array. Each finding must have:
file_path: string
line_number: integer — the exact line number from the FULL FILE WITH LINE NUMBERS block (left side of the |). This field MUST be called line_number, NOT file_number. Example: if the code shows 42 | def foo():, then line_number is 42.
severity: "major" or "critical" (DO NOT return "minor")
category: "code_quality"
description: string (clear explanation of the severe logic error or bug)
suggestion: string (exactly how to fix it)
confidence: float (0.0 to 1.0)

Return ONLY the JSON array, no other text. If no issues found, return [].
"""

    try:
        response_text = _call_bedrock(prompt)
        # Strip markdown code fences if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        findings = json.loads(cleaned)
        if not isinstance(findings, list):
            findings = []

        log.info("code_quality_review_done", findings_count=len(findings))
        return {"findings": findings}

    except Exception as e:
        log.error("code_quality_review_error", error=str(e))
        return {"findings": []}