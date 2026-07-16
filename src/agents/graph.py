import structlog
from langgraph.graph import StateGraph, START, END
from src.agents.state import PRReviewState
from src.agents.nodes import (
    ingestion,
    context_retrieval,
    code_quality,
    security_audit,
    performance,
    aider_llm_fix,
    create_agent_pr,
    publish_review,
)
from src.agents.nodes import ci_status, aider_ci_fix
from src.agents.nodes.fetch_pr_agent_suggestions import fetch_pr_agent_suggestions_node
from src.config.settings import settings

log = structlog.get_logger()


def _route_after_ci_check(state: PRReviewState) -> str:
    """
    Conditional edge after ci_status node.

    - CI passed                              → proceed to LLM review
    - CI failed AND attempts < max_retries   → try Aider CI fix (loop back)
    - CI failed AND attempts >= max_retries  → force-continue to LLM review
    """
    if state.ci_passed:
        log.info("ci_route_passed", pr_id=state.pr_id)
        return "context_retrieval"

    if state.ci_fix_attempts >= settings.AIDER_MAX_CI_RETRIES:
        log.warning(
            "ci_route_max_retries_force_continue",
            pr_id=state.pr_id,
            attempts=state.ci_fix_attempts,
            max=settings.AIDER_MAX_CI_RETRIES,
        )
        return "context_retrieval"  # Force continue — CI failure noted in PR comment

    log.info(
        "ci_route_failed_will_fix",
        pr_id=state.pr_id,
        attempt=state.ci_fix_attempts + 1,
        max=settings.AIDER_MAX_CI_RETRIES,
    )
    return "aider_ci_fix"


def build_graph() -> StateGraph:
    builder = StateGraph(PRReviewState)

    # ── Core nodes ──────────────────────────────────────────────────────────
    builder.add_node("pr_ingestion",              ingestion.run)
    builder.add_node("ci_status",                 ci_status.run)        # NEW
    builder.add_node("aider_ci_fix",              aider_ci_fix.run)     # NEW
    builder.add_node("context_retrieval",         context_retrieval.run)
    builder.add_node("code_quality",              code_quality.run)
    builder.add_node("security_audit",            security_audit.run)
    builder.add_node("performance_analysis",      performance.run)
    builder.add_node("fetch_pr_agent_suggestions",fetch_pr_agent_suggestions_node)
    builder.add_node("aider_llm_fix",             aider_llm_fix.run)
    builder.add_node("create_agent_pr",           create_agent_pr.run)
    builder.add_node("publish_review",            publish_review.run)

    # ── Edges ───────────────────────────────────────────────────────────────
    # 1. Ingestion → CI check
    builder.add_edge(START, "pr_ingestion")
    builder.add_edge("pr_ingestion", "ci_status")

    # 2. CI check → conditional route (pass → review | fail → fix → loop)
    builder.add_conditional_edges(
        "ci_status",
        _route_after_ci_check,
        {
            "context_retrieval": "context_retrieval",
            "aider_ci_fix":      "aider_ci_fix",
        },
    )

    # 3. CI fix loops back to CI check (creates the retry cycle)
    builder.add_edge("aider_ci_fix", "ci_status")

    # 4. Context → parallel fan-out to 3 LLM agents
    builder.add_edge("context_retrieval",    "code_quality")
    builder.add_edge("context_retrieval",    "security_audit")
    builder.add_edge("context_retrieval",    "performance_analysis")

    # 5. Parallel fan-in → PR-Agent judge
    builder.add_edge("code_quality",         "fetch_pr_agent_suggestions")
    builder.add_edge("security_audit",       "fetch_pr_agent_suggestions")
    builder.add_edge("performance_analysis", "fetch_pr_agent_suggestions")

    # 6. Judge → Aider auto-fix → create agent PR → publish review → done
    builder.add_edge("fetch_pr_agent_suggestions", "aider_llm_fix")
    builder.add_edge("aider_llm_fix",              "create_agent_pr")
    builder.add_edge("create_agent_pr",            "publish_review")
    builder.add_edge("publish_review",             END)

    return builder.compile()


graph = build_graph()