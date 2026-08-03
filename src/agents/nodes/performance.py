import structlog
from src.agents.prompts.performance import build_performance_prompt
from src.agents.state import PRReviewState
from src.agents.utils.llm import build_file_context, call_bedrock_review

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """Reviews code for performance issues using Bedrock Nova Pro."""
    log.info("performance_review_start")

    if not state.file_contents:
        return {"findings": []}

    files_text = build_file_context(state)
    prompt = build_performance_prompt(files_text)

    try:
        findings = call_bedrock_review(prompt)
        log.info("performance_review_done", findings_count=len(findings))
        return {"findings": findings}
    except Exception as e:
        log.error("performance_review_error", error=str(e))
        return {"findings": []}