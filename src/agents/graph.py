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
from src.agents.nodes.fetch_pr_agent_suggestions import fetch_pr_agent_suggestions_node

log = structlog.get_logger()


def build_graph() -> StateGraph:
    builder = StateGraph(PRReviewState)

    # ── Core nodes ──────────────────────────────────────────────────────────
    builder.add_node("pr_ingestion",              ingestion.run)
    builder.add_node("context_retrieval",         context_retrieval.run)
    builder.add_node("code_quality",              code_quality.run)
    builder.add_node("security_audit",            security_audit.run)
    builder.add_node("performance_analysis",      performance.run)
    builder.add_node("fetch_pr_agent_suggestions",fetch_pr_agent_suggestions_node)
    builder.add_node("aider_llm_fix",             aider_llm_fix.run)
    builder.add_node("create_agent_pr",           create_agent_pr.run)
    builder.add_node("publish_review",            publish_review.run)

    # ── Edges ───────────────────────────────────────────────────────────────
    # 1. Ingestion → Context Retrieval
    builder.add_edge(START, "pr_ingestion")
    builder.add_edge("pr_ingestion", "context_retrieval")

    # 2. Context → parallel fan-out to 3 LLM agents
    builder.add_edge("context_retrieval",    "code_quality")
    builder.add_edge("context_retrieval",    "security_audit")
    builder.add_edge("context_retrieval",    "performance_analysis")

    # 3. Parallel fan-in → PR-Agent judge
    builder.add_edge("code_quality",         "fetch_pr_agent_suggestions")
    builder.add_edge("security_audit",       "fetch_pr_agent_suggestions")
    builder.add_edge("performance_analysis", "fetch_pr_agent_suggestions")

    # 4. Judge → Aider auto-fix → create agent PR → publish review → done
    builder.add_edge("fetch_pr_agent_suggestions", "aider_llm_fix")
    builder.add_edge("aider_llm_fix",              "create_agent_pr")
    builder.add_edge("create_agent_pr",            "publish_review")
    builder.add_edge("publish_review",             END)

    return builder.compile()


graph = build_graph()