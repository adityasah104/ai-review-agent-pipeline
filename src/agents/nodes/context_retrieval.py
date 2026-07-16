import structlog
import os
from src.agents.state import PRReviewState

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """
    Reads relevant Python and dbt guidelines directly from disk
    based on what file types changed in the PR.
    """
    log.info("context_retrieval_start")

    file_types = list(set(f["file_type"] for f in state.changed_files))
    context = []

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    guidelines_dir = os.path.join(base_dir, "guidelines")

    if "python" in file_types:
        try:
            with open(os.path.join(guidelines_dir, "python_guidelines.md"), "r") as f:
                context.append(f"### Python Guidelines ###\n{f.read()}")
        except Exception as e:
            log.warning("failed_to_read_python_guidelines", error=str(e))

    if "sql" in file_types:
        try:
            with open(os.path.join(guidelines_dir, "dbt_guidelines.md"), "r") as f:
                context.append(f"### dbt/SQL Guidelines ###\n{f.read()}")
        except Exception as e:
            log.warning("failed_to_read_dbt_guidelines", error=str(e))

    log.info("context_retrieval_done", chunks=len(context))
    return {"rag_context": context}