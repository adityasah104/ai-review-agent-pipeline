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
    publish_review,
)
from src.agents.nodes.fetch_pr_agent_suggestions import fetch_pr_agent_suggestions_node

log = structlog.get_logger()

def build_graph() -> StateGraph:
    builder = StateGraph(PRReviewState)

    # Register all nodes
    builder.add_node("pr_ingestion", ingestion.run)
    builder.add_node("context_retrieval", context_retrieval.run)
    builder.add_node("code_quality", code_quality.run)
    builder.add_node("security_audit", security_audit.run)
    builder.add_node("performance_analysis", performance.run)
    builder.add_node("fetch_pr_agent_suggestions", fetch_pr_agent_suggestions_node)
    builder.add_node("aider_llm_fix", aider_llm_fix.run)
    builder.add_node("publish_review", publish_review.run)

    # Entry point directly jumps to context_retrieval after ingestion
    builder.add_edge(START, "pr_ingestion")
    builder.add_edge("pr_ingestion", "context_retrieval")

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