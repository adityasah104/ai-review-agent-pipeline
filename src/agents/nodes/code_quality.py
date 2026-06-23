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
            "maxTokens": 2000,
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

    # Build file text — prefer diff (focused), fall back to full content
    files_text = ""
    for path, content in state.file_contents.items():
        diff = state.file_diffs.get(path)
        if diff:
            files_text += (
                f"\n\n### File: {path} (changed lines only)\n"
                f"```diff\n{diff[:4000]}\n```"
            )
        else:
            truncated = content[:3000] if len(content) > 3000 else content
            files_text += f"\n\n### File: {path}\n```\n{truncated}\n```"

    rag_text = "\n".join(state.rag_context[:4]) if state.rag_context else "No guidelines available."

    prompt = f"""You are a senior code reviewer specializing in Python and dbt/SQL.

Relevant coding guidelines from our internal standards:
{rag_text}

Review the following code changes for CODE QUALITY issues only.
Look for:
- PEP 8 violations in Python
- Poor naming conventions
- Missing docstrings on functions/classes
- Overly complex functions (too many lines, too many parameters)
- Hardcoded values that should be constants or config
- dbt model naming convention violations (stg_, mart_, int_ prefixes)
- Missing {{ ref() }} or {{ source() }} macro usage in dbt SQL
- SELECT * usage in SQL models

Changed code (unified diff — lines starting with + are additions, - are deletions):
{files_text}

IMPORTANT: Only report issues introduced in the changed lines (+ lines in the diff).
Do NOT flag pre-existing issues in unchanged context lines.

Return your findings as a JSON array. Each finding must have:
- file_path: string
- line_hint: string (e.g. "line 12" or "throughout file")  
- severity: "major" or "minor"
- category: "code_quality"
- description: string (clear explanation of the issue)
- suggestion: string (exactly how to fix it)
- confidence: float (0.0 to 1.0, where 1.0 is absolute certainty and 0.5 is a guess)

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