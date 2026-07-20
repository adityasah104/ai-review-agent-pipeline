import time
import httpx
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings
from src.db.database import SessionLocal
from src.db.models import ReviewJob

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
        - Ensures file_path is always present
        - Fixes hallucinated 'file_number' -> 'line_number'
        - Ensures line_number is always an integer
        - Keeps only known fields PR-Agent's schema expects
        """
        # Fix hallucinated field name
        if "file_number" in f and "line_number" not in f:
            f["line_number"] = f.pop("file_number")

        # Ensure line_number is an integer
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

    # 1. Send data to PR-Agent (sanitized)
    sanitized = [sanitize_finding(f) for f in findings if f.get("file_path") or f.get("file_number")]
    payload = {
        "pr_id": pr_id,
        "my_suggestions": sanitized
    }

    print("\n--- FINDINGS BEING SENT TO PR_AGENT ---")
    print(json.dumps(payload, indent=2))
    print("--------------------------------------\n")

    # 2. RUN PR AGENT NATIVELY (NO NETWORK CALL)
    try:
        import sys
        import os
        import asyncio
        
        # Dynamically add pr-agent to sys.path so we can import it
        pr_agent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../pr-agent-latest-"))
        if pr_agent_path not in sys.path:
            sys.path.insert(0, pr_agent_path)
            
        from pr_agent.app18 import receive_findings, IncomingFindingsPayload
        
        payload_model = IncomingFindingsPayload(pr_id=pr_id, my_suggestions=sanitized)
        log.info("running_pr_agent_natively", pr_id=pr_id)
        
        # Safely get or create an event loop to run the async PR-Agent function
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            # If we're already inside an async context (e.g. LangGraph ainvoke), we must await it directly
            # Wait, this node is defined as `def`, not `async def`. But just in case:
            import nest_asyncio
            nest_asyncio.apply()
            
        result = loop.run_until_complete(receive_findings(payload_model))
        
        refined_findings = result.get("refined_findings", [])
        log.info("received_refined_findings_from_pr_agent_natively", pr_id=pr_id, count=len(refined_findings))
        
        # Update the database to mark it received
        db = SessionLocal()
        try:
            job = db.query(ReviewJob).filter(ReviewJob.id == state.job_id).first()
            if job:
                job.refined_findings = refined_findings
                job.refined_findings_received = True
                db.commit()
        finally:
            db.close()
            
        return {"refined_findings": refined_findings}
        
    except Exception as e:
        log.error("failed_to_run_pr_agent_natively", error=str(e))
        return {"refined_findings": findings} # Fallback