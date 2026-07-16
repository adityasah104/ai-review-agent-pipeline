import json
import structlog
import asyncio
import sys
import os
from src.agents.state import PRReviewState
from src.config.settings import settings

log = structlog.get_logger()

def fetch_pr_agent_suggestions_node(state: PRReviewState) -> dict:
    pr_id = state.pr_id
    findings = state.findings

    if not findings:
        return {"refined_findings": []}

    def sanitize_finding(f: dict) -> dict:
        if "file_number" in f and "line_number" not in f:
            f["line_number"] = f.pop("file_number")

        raw_line = f.get("line_number")
        if raw_line is not None:
            try:
                f["line_number"] = int(str(raw_line).replace("Line", "").strip())
            except (ValueError, TypeError):
                f["line_number"] = None

        return {
            "file_path":   f.get("file_path", ""),
            "line_number": f.get("line_number"),
            "severity":    f.get("severity", "major"),
            "category":    f.get("category", "code_quality"),
            "description": f.get("description", ""),
            "suggestion":  f.get("suggestion", ""),
            "confidence":  float(f.get("confidence", 1.0)),
        }

    sanitized = [sanitize_finding(f) for f in findings if f.get("file_path") or f.get("file_number")]
    
    # Try importing PR Agent directly to avoid HTTP IPC overhead
    try:
        from pr_agent.app18 import receive_findings, IncomingFindingsPayload, IncomingSuggestionItem
    except ImportError:
        log.warning("pr_agent_import_failed", msg="Could not import pr_agent. Falling back to original findings.")
        return {"refined_findings": findings}

    # Construct the payload models natively
    suggestion_items = [IncomingSuggestionItem(**item) for item in sanitized]
    payload = IncomingFindingsPayload(pr_id=pr_id, my_suggestions=suggestion_items)

    print("\n--- FINDINGS BEING SENT TO PR_AGENT (DIRECT IMPORT) ---")
    print(json.dumps([s.dict() for s in suggestion_items], indent=2))
    print("--------------------------------------\n")

    try:
        # Call the asynchronous FastAPI route function directly
        result_dict = asyncio.run(receive_findings(payload))
        
        refined_findings = result_dict.get("refined_findings", [])
        log.info("received_refined_findings_from_pr_agent", pr_id=pr_id)
        
        print("\n=== REFINED FINDINGS RECEIVED FROM PR_AGENT ===")
        print(json.dumps(refined_findings, indent=2))
        print("==============================================\n")
        
        return {"refined_findings": refined_findings}
    except Exception as e:
        log.error("failed_to_get_suggestions_from_pr_agent", error=str(e))
        return {"refined_findings": findings} # Fallback