import structlog
from src.agents.prompts.code_quality import build_code_quality_prompt
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
    prompt = build_code_quality_prompt(files_text)

    try:
        findings = call_bedrock_review(prompt)
        log.info("code_quality_review_done", findings_count=len(findings))
        return {"findings": findings}
    except Exception as e:
        log.error("code_quality_review_error", error=str(e))
        return {"findings": []}