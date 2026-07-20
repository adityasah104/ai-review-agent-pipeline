import structlog
from src.agents.state import PRReviewState

log = structlog.get_logger()

def fetch_pr_agent_suggestions_node(state: PRReviewState) -> dict:
    pr_id = state.pr_id
    findings = state.findings

    if not findings:
        return {"refined_findings": []}

    import json

    def sanitize_finding(f: dict) -> dict:
        """
        Cleans a finding before sending to PR-Agent.
        """
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
    
    print("\n--- FINDINGS BEING PASSED TO PR_AGENT NATIVELY ---")
    print(json.dumps(sanitized, indent=2))
    print("--------------------------------------\n")

    try:
        import sys
        import os
        import asyncio
        import concurrent.futures
        
        # Dynamically add pr-agent to sys.path so we can import it
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
        pr_agent_path = os.path.join(base_dir, "pr-agent-latest-")
        if not os.path.exists(pr_agent_path):
            pr_agent_path = os.path.join(base_dir, "michael_repo") # ADO Pipeline folder name
            
        if pr_agent_path not in sys.path:
            sys.path.insert(0, pr_agent_path)
            
        from pr_agent.app18 import receive_findings, IncomingFindingsPayload
        
        payload_model = IncomingFindingsPayload(pr_id=pr_id, my_suggestions=sanitized)
        log.info("running_pr_agent_natively", pr_id=pr_id)
        
        # Run the async PR-Agent function safely in a separate thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, receive_findings(payload_model))
            result = future.result()
        
        refined_findings = result.get("refined_findings", [])
        log.info("received_refined_findings_from_pr_agent_natively", pr_id=pr_id, count=len(refined_findings))
            
        return {"refined_findings": refined_findings}
        
    except Exception as e:
        log.error("failed_to_run_pr_agent_natively", error=str(e))
        return {"refined_findings": findings} # Fallback