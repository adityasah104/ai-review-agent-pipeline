import structlog
from langgraph.graph import StateGraph, START, END
from src.agents.state import PRReviewState
from src.agents.nodes import (
    ingestion,
    ci_status,
    aider_ci_fix,
    context_retrieval,
    code_quality,
    security_audit,
    performance,
    aider_llm_fix,
    publish_review,
)
from src.config.settings import settings
from src.agents.nodes.fetch_pr_agent_suggestions import fetch_pr_agent_suggestions_node

log = structlog.get_logger()


def route_after_ci_check(state: PRReviewState) -> str:
    """
    After checking CI status:
    - If CI passed → continue to context retrieval (LLM review)
    - If CI failed AND retries not exhausted → run Aider CI fix
    - If CI failed AND retries exhausted → continue anyway (give up fixing)
    """
    if state.ci_passed:
        return "context_retrieval"

    if state.ci_fix_attempts < settings.AIDER_MAX_CI_RETRIES:
        return "aider_ci_fix"

    # Max retries reached — continue to review regardless
    log.warning("ci_fix_max_retries_skip", attempts=state.ci_fix_attempts)
    return "context_retrieval"


def route_after_aider_ci_fix(state: PRReviewState) -> str:
    """
    After Aider attempts a CI fix:
    - Always go back to ci_status to re-check
    - The ci_status node will wait for the new build triggered by the push
    """
    return "ci_status"


def build_graph() -> StateGraph:
    builder = StateGraph(PRReviewState)

    # Register all nodes
    builder.add_node("pr_ingestion", ingestion.run)
    builder.add_node("ci_status", ci_status.run)
    builder.add_node("aider_ci_fix", aider_ci_fix.run)
    builder.add_node("context_retrieval", context_retrieval.run)
    builder.add_node("code_quality", code_quality.run)
    builder.add_node("security_audit", security_audit.run)
    builder.add_node("performance_analysis", performance.run)
    
    # NEW: Fetch PR-Agent's suggestions node
    builder.add_node("fetch_pr_agent_suggestions", fetch_pr_agent_suggestions_node)
    
    builder.add_node("aider_llm_fix", aider_llm_fix.run)
    builder.add_node("publish_review", publish_review.run)

    # Entry point
    builder.add_edge(START, "pr_ingestion")
    builder.add_edge("pr_ingestion", "ci_status")

    # CI routing — this is where the anti-loop logic lives
    builder.add_conditional_edges(
        "ci_status",
        route_after_ci_check,
        {
            "context_retrieval": "context_retrieval",
            "aider_ci_fix": "aider_ci_fix",
        },
    )

    # After Aider CI fix → always go back to ci_status (re-check)
    builder.add_conditional_edges(
        "aider_ci_fix",
        route_after_aider_ci_fix,
        {"ci_status": "ci_status"},
    )

    # After context retrieval → all three LLM agents run in parallel
    builder.add_edge("context_retrieval", "code_quality")
    builder.add_edge("context_retrieval", "security_audit")
    builder.add_edge("context_retrieval", "performance_analysis")

    # All three LLM agents → fetch_pr_agent_suggestions (fan-in)
    builder.add_edge("code_quality", "fetch_pr_agent_suggestions")
    builder.add_edge("security_audit", "fetch_pr_agent_suggestions")
    builder.add_edge("performance_analysis", "fetch_pr_agent_suggestions")

    # fetch_pr_agent_suggestions → Aider LLM fix
    builder.add_edge("fetch_pr_agent_suggestions", "aider_llm_fix")

    # Aider LLM fix → publish review
    builder.add_edge("aider_llm_fix", "publish_review")
    builder.add_edge("publish_review", END)

    return builder.compile()


# Module-level compiled graph instance
graph = build_graph()