from typing import List, Dict, Any, Annotated, Optional
from pydantic import BaseModel, Field


def append_findings(current: List[Dict], update: List[Dict]) -> List[Dict]:
    """Merge-safe reducer for parallel agent findings. Prevents fan-out overwrites."""
    return current + update


class PRReviewState(BaseModel):
    # Job tracking
    job_id: int = Field(..., description="SQLite review_jobs.id")

    # PR metadata from Azure DevOps
    pr_id: int
    repository_id: str
    project: str
    source_branch: str
    target_branch: str
    pr_url: str = ""
    pr_title: str = ""

    # Diff content fetched from Azure DevOps
    changed_files: List[Dict[str, Any]] = Field(default_factory=list)
    file_contents: Dict[str, str] = Field(default_factory=dict)
    # key: file path, value: raw content
    file_diffs: Dict[str, str] = Field(default_factory=dict)
    # key: file path, value: unified diff of only the changed lines

    # CI status
    ci_passed: Optional[bool] = None
    ci_build_id: Optional[int] = None
    ci_log_summary: str = ""
    ci_fix_attempts: int = 0

    # RAG context from ChromaDB
    rag_context: List[str] = Field(default_factory=list)

    # Parallel LLM agent findings — uses append reducer to avoid fan-out overwrite
    findings: Annotated[List[Dict[str, Any]], append_findings] = Field(default_factory=list)

    # Aider LLM fix output
    aider_fix_summary: str = ""
    aider_fix_applied: bool = False

    # Final review summary posted as PR comment
    review_summary: str = ""

    # Control flow
    status: str = "INIT"
    error: str = ""