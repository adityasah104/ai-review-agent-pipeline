import json
import boto3
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings

log = structlog.get_logger()


def _call_bedrock(prompt: str) -> str:
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
    """Reviews code for performance issues using Bedrock Nova Pro."""
    log.info("performance_review_start")

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

    prompt = f"""You are a performance engineering expert reviewing Python and SQL code.

Review the following code for PERFORMANCE issues only.
Look for:
- N+1 query patterns in Python (loops that execute database queries)
- Missing indexes implied by filter/join columns in SQL
- SELECT * in SQL (fetches unnecessary columns)
- Large result sets loaded entirely into memory in Python
- Inefficient list comprehensions vs generators for large data
- dbt models missing incremental materializations for large tables
- Repeated expensive function calls inside loops
- SQL DISTINCT or ORDER BY on large unsorted datasets without purpose

Changed code (unified diff — lines starting with + are additions, - are deletions):
{files_text}

IMPORTANT: Only report issues introduced in the changed lines (+ lines in the diff).
Do NOT flag pre-existing issues in unchanged context lines.

Return your findings as a JSON array. Each finding must have:
- file_path: string
- line_hint: string
- severity: "major" or "minor"
- category: "performance"
- description: string
- suggestion: string
- confidence: float (0.0 to 1.0, where 1.0 is absolute certainty and 0.5 is a guess)

Return ONLY the JSON array, no other text. If no issues found, return [].
"""

    try:
        response_text = _call_bedrock(prompt)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        findings = json.loads(cleaned)
        if not isinstance(findings, list):
            findings = []

        log.info("performance_review_done", findings_count=len(findings))
        return {"findings": findings}

    except Exception as e:
        log.error("performance_review_error", error=str(e))
        return {"findings": []}