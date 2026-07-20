import json
import httpx
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings

log = structlog.get_logger()

async def fetch_pr_agent_suggestions_node(state: PRReviewState) -> dict:
    pr_id = state.pr_id
    findings = state.findings

    if not findings:
        return {"refined_findings": []}

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
        # Async request with long timeout since PR-Agent runs on localhost
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(settings.PR_AGENT_REFINE_URL, json=payload)
        response.raise_for_status()
        
        refined_findings = response.json().get("refined_findings", [])
        log.info("received_refined_findings_from_pr_agent", pr_id=pr_id)
        
        print("\n=== REFINED FINDINGS RECEIVED FROM PR_AGENT ===")
        print(json.dumps(refined_findings, indent=2))
        print("==============================================\n")
        
        return {"refined_findings": refined_findings}
    except Exception as e:
        log.error("failed_to_get_suggestions_from_pr_agent", error=str(e))
        return {"refined_findings": findings} # Fallback