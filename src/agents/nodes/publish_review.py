import structlog
from src.agents.state import PRReviewState
from src.azure_client.pr_client import post_pr_comment
from src.config.settings import settings

log = structlog.get_logger()

SEVERITY_BADGE = {
    "critical": "CRITICAL",
    "major":    "MAJOR",
    "minor":    "MINOR",
    "info":     "INFO",
}

CATEGORY_LABEL = {
    "code_quality": "Code Quality",
    "security":     "Security",
    "performance":  "Performance",
}


def _findings_table(findings: list, lines: list) -> None:
    """Renders a single markdown table with findings and their corresponding fixes."""
    lines.append("| Severity | File | Location | Confidence | Issue | Fix Applied |")
    lines.append("|----------|------|----------|------------|-------|-------------|")

    for f in findings:
        severity  = f.get("severity", "minor")
        badge     = SEVERITY_BADGE.get(severity, severity.upper())
        file_path = f.get("file_path", "")
        line_hint = f.get("line_hint", f.get("line_number", "—"))
        if not line_hint or str(line_hint).strip().lower() in ("none-none", "none", "null"):
            line_hint = "—"
            
        conf_val  = float(f.get("confidence", 0.0))
        conf_pct  = f"{int(conf_val * 100)}%"
        desc      = f.get("description", "").replace("|", "\\|")
        suggestion = f.get("suggestion", "").replace("|", "\\|")

        skipped = ""
        if conf_val < settings.MIN_FIX_CONFIDENCE:
            skipped = " *(auto-fix skipped)*"

        lines.append(
            f"| {badge} | `{file_path}` | {line_hint} | {conf_pct} | {desc} | {suggestion}{skipped} |"
        )
    lines.append("")


def _build_comment(state: PRReviewState) -> str:
    lines = []

    lines.append("## AI Code Review")
    lines.append("")
    # Tag the actual PR author by their ADO unique name using < > so it becomes clickable
    author_tag = f"@<{state.pr_author_id}>" if state.pr_author_id else "@Author"
    lines.append(f"cc: {author_tag}")
    lines.append("")
    
    if state.status == "CI_FIX_GAVE_UP":
        lines.append("> **Warning:** Attempted CI fixes but pipeline is still failing. Manual intervention required.")
        lines.append("")

    lines.append("")

    # Use refined findings if available, otherwise fallback to raw findings
    findings = state.refined_findings if state.refined_findings else state.findings
    
    high_confidence_findings = [f for f in findings if float(f.get("confidence", 0.0)) >= settings.MIN_FIX_CONFIDENCE]
    low_confidence_findings = [f for f in findings if float(f.get("confidence", 0.0)) < settings.MIN_FIX_CONFIDENCE]

    if high_confidence_findings:
        lines.append("Review-agent found these issues and applied fixes on a separate agent branch:")
        lines.append("")
        _findings_table(high_confidence_findings, lines)
        if low_confidence_findings:
            lines.append("### ⚠️ Additional Low-Confidence Findings")
            lines.append("The following issues were flagged but skipped for auto-fixing due to low confidence:")
            lines.append("")
            _findings_table(low_confidence_findings, lines)
    elif low_confidence_findings:
        lines.append("### ✅ Code is mostly Good to Go!")
        lines.append("")
        lines.append("There were no high-confidence issues that required agent auto-fixes, but the following low-confidence issues were flagged for your review:")
        lines.append("")
        _findings_table(low_confidence_findings, lines)
    else:
        lines.append("### ✅ Code is Good to Go!")
        lines.append("")
        lines.append("I have reviewed the changes in this PR and found no issues. No agent branch or fixes were needed.")
        lines.append("")

    return "\n".join(lines)


async def run(state: PRReviewState) -> dict:
    """Posts the final review summary as a PR comment in Azure DevOps."""
    log.info("publish_review_start", pr_id=state.pr_id, findings=len(state.findings))

    comment = _build_comment(state)

    try:
        await post_pr_comment(state.repository_id, state.pr_id, comment)
        log.info("publish_review_done")
        return {"review_summary": comment, "status": "DONE"}
    except Exception as e:
        log.error("publish_review_error", error=str(e))
        return {"status": "FAILED", "error": f"Failed to post PR comment: {e}"}