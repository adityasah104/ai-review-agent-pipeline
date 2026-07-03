from typing import List, Dict, Any, Annotated, Optional
from pydantic import BaseModel, Field


import difflib

def append_findings(current: List[Dict], update: List[Dict]) -> List[Dict]:
    """Merge-safe reducer with fuzzy deduplication to prevent AI overlaps."""
    combined = current + update
    unique = []
    
    for new_f in combined:
        is_duplicate = False
        for ex_f in unique:
            # Only compare findings in the same file
            if new_f.get("file_path") == ex_f.get("file_path"):
                new_sug = str(new_f.get("suggestion", "")).lower()
                ex_sug = str(ex_f.get("suggestion", "")).lower()
                
                # Use difflib to check how similar the suggestions are
                similarity = difflib.SequenceMatcher(None, new_sug, ex_sug).ratio()
                
                # If they are more than 45% similar, treat them as duplicates
                if similarity > 0.45:
                    is_duplicate = True
                    # Keep the one with the highest confidence
                    if float(new_f.get("confidence", 0.0)) > float(ex_f.get("confidence", 0.0)):
                        ex_f.clear()
                        ex_f.update(new_f)
                    break
                    
        if not is_duplicate:
            unique.append(new_f.copy())
            
    return unique


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

    #NEW Hybrid Integration
    refined_findings: List[Dict[str, Any]] = Field(default_factory=list)