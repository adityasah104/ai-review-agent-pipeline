import json
import boto3
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings

log = structlog.get_logger()


def _call_bedrock(prompt: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
    body = {
        "system": [{"text": "You are a strict code review assistant. You ONLY report issues that exactly match the explicit checklist given to you. You do NOT use general knowledge, common sense, or best-practice opinions outside of what is explicitly listed. If a pattern is not in the checklist, you MUST ignore it entirely."}],
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
    """Reviews code for security vulnerabilities using Bedrock Nova Pro."""
    log.info("security_audit_start")

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
        files_text += f"--- FULL FILE WITH LINE NUMBERS ---\n```\n{numbered_content[:8000]}\n```\n"
        files_text += f"--- CHANGED LINES (diff) ---\n```diff\n{diff[:4000]}\n```\n"

    rag_text = "\n".join(state.rag_context[:2]) if state.rag_context else ""

    prompt = f"""You are a ruthless security engineer reviewing Python and SQL code for vulnerabilities.

{f"Relevant security guidelines: {rag_text}" if rag_text else ""}

CRITICAL RULES (violating any of these makes your review invalid):
1. DO NOT invent or hallucinate issues. If the code is perfectly fine, return an empty
   array []. You are NOT required to find a problem. Zero findings is a completely
   normal, acceptable, and often correct result.
2. DO NOT change or complain about business logic.
3. YOU MUST ONLY CHECK FOR THE ISSUES IN THE STRICT CHECKLIST BELOW. Do NOT use your general knowledge.

Review the following code for SEVERE SECURITY issues only.
You MUST ONLY report actionable vulnerabilities that require an immediate code change.
DO NOT report theoretical risks, subjective security "best practices", or minor nitpicks.

STRICT CHECKLIST - Look ONLY for these exact issues:
- SQL injection risks (string concatenation in SQL instead of parameterized queries)
- Hardcoded credentials, API keys, passwords, or tokens
- Insecure use of eval() or exec() in Python
- Missing input validation that leads to direct exploits
- Exposure of sensitive data in logs or error messages
- Use of deprecated or insecure Python functions (e.g. pickle, md5)
- SQL models exposing PII columns without masking

Here is the code context. You are provided with the full file (with line numbers on the left) and the git diff:
{files_text}

IMPORTANT: Only report issues introduced in the changed lines (shown in the diff).
Do NOT flag pre-existing issues in unchanged context lines.
If an issue does not absolutely require a code change, IGNORE IT.

Return your findings as a JSON array. Each finding must have:
- file_path: string
- line_number: integer — the exact line number from the FULL FILE WITH LINE NUMBERS block (left side of the `|`). This field MUST be called `line_number`, NOT `file_number`. Example: if the code shows `42 | def foo():`, then line_number is 42.
- severity: "critical" or "major" (DO NOT return "minor")
- category: "security"
- description: string (clear explanation of the exploit or vulnerability)
- suggestion: string
- confidence: float (0.0 to 1.0)

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