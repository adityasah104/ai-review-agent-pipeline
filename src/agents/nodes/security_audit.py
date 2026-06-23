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
    """Reviews code for security vulnerabilities using Bedrock Nova Pro."""
    log.info("security_audit_start")

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

    rag_text = "\n".join(state.rag_context[:2]) if state.rag_context else ""

    prompt = f"""You are a security engineer reviewing Python and SQL code for vulnerabilities.

{f"Relevant security guidelines: {rag_text}" if rag_text else ""}

Review the following code for SECURITY issues only.
Look for:
- SQL injection risks (string concatenation in SQL instead of parameterized queries)
- Hardcoded credentials, API keys, passwords, or tokens
- Insecure use of eval() or exec() in Python
- Missing input validation
- Exposure of sensitive data in logs or error messages
- Use of deprecated or insecure Python functions (e.g. pickle, md5)
- SQL models exposing PII columns without masking

Changed code (unified diff — lines starting with + are additions, - are deletions):
{files_text}

IMPORTANT: Only report issues introduced in the changed lines (+ lines in the diff).
Do NOT flag pre-existing issues in unchanged context lines.

Return your findings as a JSON array. Each finding must have:
- file_path: string
- line_hint: string
- severity: "critical" or "major"
- category: "security"
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

        log.info("security_audit_done", findings_count=len(findings))
        return {"findings": findings}

    except Exception as e:
        log.error("security_audit_error", error=str(e))
        return {"findings": []}