import structlog
from src.agents.prompts.security import build_security_prompt
from src.agents.state import PRReviewState
from src.agents.utils.llm import build_file_context, call_bedrock_review

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """Reviews code for security vulnerabilities using Bedrock Nova Pro."""
    log.info("security_audit_start")

    if not state.file_contents:
        return {"findings": []}

    files_text = build_file_context(state)
    prompt = build_security_prompt(files_text)

    try:
        findings = call_bedrock_review(prompt)
        log.info("security_audit_done", findings_count=len(findings))
        return {"findings": findings}
    except Exception as e:
        log.error("security_audit_error", error=str(e))
        return {"findings": []}