import json
import structlog
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Any
from src.gateway.signature import validate_azure_webhook
from src.db.database import SessionLocal
from src.db.models import ReviewJob

log = structlog.get_logger()
router = APIRouter()


def _enqueue_job(payload: dict) -> ReviewJob:
    """
    Parses the Azure DevOps Service Hook payload and inserts a PENDING job
    into the SQLite review_jobs table.
    """
    resource = payload.get("resource", {})
    repo = resource.get("repository", {})
    pr = resource

    job = ReviewJob(
        status="PENDING",
        pr_id=pr.get("pullRequestId"),
        repository_id=repo.get("id", ""),
        project=repo.get("project", {}).get("name", ""),
        source_branch=pr.get("sourceRefName", ""),
        target_branch=pr.get("targetRefName", ""),
        pr_url=pr.get("url", ""),
        pr_title=pr.get("title", ""),
        raw_payload=payload,
    )

    db: Session = SessionLocal()
    try:
        db.add(job)
        db.commit()
        db.refresh(job)
        log.info("job_enqueued", job_id=job.id, pr_id=job.pr_id)
        return job
    finally:
        db.close()


@router.post("/webhook/azure/pr", status_code=202)
async def receive_pr_webhook(request: Request):
    """
    Receives Azure DevOps Service Hook events for Pull Request Created/Updated.
    Returns HTTP 202 immediately. Processing happens in background worker thread.
    """
    body = await validate_azure_webhook(request)
    payload = json.loads(body)

    event_type = payload.get("eventType", "")
    log.info("webhook_received", event_type=event_type)

    # Only process PR created or updated events
    if event_type not in (
        "git.pullrequest.created",
        "git.pullrequest.updated",
    ):
        return {"status": "ignored", "reason": f"event_type={event_type}"}

    resource = payload.get("resource", {})

    # Only process PRs targeting main branch
    target_branch = resource.get("targetRefName", "")
    if "main" not in target_branch and "master" not in target_branch:
        return {"status": "ignored", "reason": "not targeting main/master"}

    # Check PR status — only process active PRs
    pr_status = resource.get("status", "")
    if pr_status not in ("active", ""):
        return {"status": "ignored", "reason": f"pr_status={pr_status}"}

    job = _enqueue_job(payload)
    return {"status": "accepted", "job_id": job.id}


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: int):
    """Check the status of a review job."""
    db = SessionLocal()
    try:
        job = db.query(ReviewJob).filter(ReviewJob.id == job_id).first()
        if not job:
            return {"error": "Job not found"}
        return {
            "id": job.id,
            "status": job.status,
            "pr_id": job.pr_id,
            "ci_fix_attempts": job.ci_fix_attempts,
            "created_at": str(job.created_at),
            "error": job.error_message,
        }
    finally:
        db.close()

#NEW Hybrid Integration

class PRAgentPayload(BaseModel):
    pr_id: int
    refined_findings: List[Dict[str, Any]]

@router.post("/api/findings/submit")
def receive_refined_findings(payload: PRAgentPayload):
    # Removed secret validation for testing purposes

    db = SessionLocal()
    try:
        job = db.query(ReviewJob).filter(ReviewJob.pr_id == payload.pr_id).order_by(ReviewJob.id.desc()).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        job.refined_findings = payload.model_dump().get("refined_findings", [])
        job.refined_findings_received = True
        db.commit()
        return {"status": "success"}
    finally:
        db.close()