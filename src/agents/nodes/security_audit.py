import textwrap
import structlog
from src.agents.state import PRReviewState
from src.agents.utils.llm import build_file_context, call_bedrock_review

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """Reviews code for security vulnerabilities using Bedrock Nova Pro."""
    log.info("security_audit_start")

    if not state.file_contents:
        return {"findings": []}

    files_text = build_file_context(state)
    rag_text = "\n".join(state.rag_context[:2]) if state.rag_context else ""
    rag_text_formatted = f"Relevant security guidelines: {rag_text}" if rag_text else ""

    prompt = f"""\
You are a ruthless security engineer reviewing Python and SQL code for vulnerabilities.

{rag_text_formatted}

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
- User-supplied value passed directly into os.system/subprocess.run(shell=True)
- File path built from request parameter without normalization/allowlist check
- Insecure deserialization (yaml.load without SafeLoader, marshal, pickle)
- SSRF, path traversal, or insecure randomness (using random for tokens/secrets instead of secrets module)
- Authorization/access-control logic errors (e.g. bypassing checks)
- Exposure of sensitive data in logs or error messages
- SQL models exposing PII columns without masking

Here is the code context. You are provided with the changed lines (diff) or the full file if no diff is available:
{files_text}

IMPORTANT: Only report issues introduced in the changed lines (if a diff is provided).
Do NOT flag pre-existing issues in unchanged context lines.
If an issue does not absolutely require a code change, IGNORE IT.

Return your findings as a JSON array. Each finding must have:
- file_path: string
- line_number: integer — the exact line number from the file. If using a diff, infer the line number from the @@ headers.
- severity: "critical" or "major" (DO NOT return "minor")
- category: "security"
- description: string (clear explanation of the exploit or vulnerability)
- suggestion: string
- confidence: float (0.0 to 1.0)
  0.9-1.0 = pattern is unambiguous and the exact vulnerable line is quoted
  0.5-0.7 = pattern matches but context is incomplete
  below 0.5 = do not include the finding at all

Return ONLY the JSON array, no other text. If no issues found, return [].
"""

    try:
        findings = call_bedrock_review(prompt)
        log.info("security_audit_done", findings_count=len(findings))
        return {"findings": findings}
    except Exception as e:
        log.error("security_audit_error", error=str(e))
        return {"findings": []}