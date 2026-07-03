from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean
from src.db.database import Base


class ReviewJob(Base):
    """
    Acts as the job queue replacing Redis/Celery.
    The background worker polls this table for PENDING jobs.
    """
    __tablename__ = "review_jobs"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(20), default="PENDING", index=True)
    # PENDING → PROCESSING → DONE | FAILED

    # PR metadata from Azure DevOps webhook payload
    pr_id = Column(Integer, nullable=False)
    repository_id = Column(String(200), nullable=False)
    project = Column(String(200), nullable=False)
    source_branch = Column(String(200), nullable=False)
    target_branch = Column(String(200), nullable=False)
    pr_url = Column(String(500), nullable=True)
    pr_title = Column(String(500), nullable=True)

    # CI retry tracking (prevents infinite loop)
    ci_fix_attempts = Column(Integer, default=0)

    # Result storage
    result_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    raw_payload = Column(JSON, nullable=True)

    #New Hybrid Integration
    refined_findings = Column(JSON, nullable=True)
    refined_findings_received = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)