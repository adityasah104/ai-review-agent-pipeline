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

    try:
        httpx.post(settings.PR_AGENT_REFINE_URL, json=payload, timeout=10.0)
        log.info("sent_findings_to_pr_agent", pr_id=pr_id)
    except Exception as e:
        log.error("failed_to_send_to_pr_agent", error=str(e))
        return {"refined_findings": findings} # Fallback

    # 2. Poll DB waiting for PR-Agent to call us back
    timeout = 300
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        db = SessionLocal()
        try:
            job = db.query(ReviewJob).filter(ReviewJob.id == state.job_id).first()
            if job and job.refined_findings_received:
                log.info("received_refined_findings_from_pr_agent", pr_id=pr_id)
                
                print("\n=== REFINED FINDINGS RECEIVED FROM PR_AGENT ===")
                print(json.dumps(job.refined_findings, indent=2))
                print("==============================================\n")
                
                return {"refined_findings": job.refined_findings}
        finally:
            db.close()
            
        time.sleep(5) # Poll every 5 seconds

    log.error("timeout_waiting_for_pr_agent", pr_id=pr_id)
    return {"refined_findings": findings} # Fallback if timeout