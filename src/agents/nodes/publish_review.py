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


def _findings_table(findings: list, lines: list, show_skipped: bool = False) -> None:
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

        skipped = " *(auto-fix skipped)*" if show_skipped else ""

        lines.append(
            f"| {badge} | `{file_path}` | {line_hint} | {conf_pct} | {desc} | {suggestion}{skipped} |"
        )
    lines.append("")


def _build_comment(state: PRReviewState) -> str:
    lines = []

    lines.append("## AI Code Review")
    lines.append("")
    # Tag the actual PR author by their ADO unique name
    author_tag = f"@<{state.pr_author_id}>" if (state.pr_author_id and state.pr_author_name) else "@Author"
    lines.append(f"cc: {author_tag}")
    lines.append("")
    
    if state.status == "CI_FIX_GAVE_UP":
        lines.append("> **Warning:** Attempted CI fixes but pipeline is still failing. Manual intervention required.")
        lines.append("")

    lines.append("")

    findings = state.refined_findings if state.refined_findings else state.findings
    
    fixed_findings = []
    skipped_findings = []
    
    for f in findings:
        conf_val = float(f.get("confidence", 0.0))
        if conf_val >= settings.MIN_FIX_CONFIDENCE:
            fixed_findings.append(f)
        else:
            skipped_findings.append(f)
            
    if fixed_findings:
        lines.append("### 🛠️ Issues Found & Fixed")
        lines.append("The review agent identified high-confidence issues and has applied automated fixes on a separate agent branch:")
        lines.append("")
        _findings_table(fixed_findings, lines, show_skipped=False)
        
        if skipped_findings:
            lines.append("### ⚠️ Potential Improvements (Manual Review Required)")
            lines.append("The following items were identified as potential issues. Due to lower confidence scores, automated fixes were not applied. Please review them manually:")
            lines.append("")
            _findings_table(skipped_findings, lines, show_skipped=True)
            
    else:
        lines.append("### ✅ Code Review Complete")
        lines.append("")
        lines.append("The review agent analyzed the changes in this pull request and found 0 high-confidence issues. No automated fixes or agent branches were necessary.")
        lines.append("")
        
        if skipped_findings:
            lines.append("### ⚠️ Potential Improvements (Manual Review Required)")
            lines.append("The following items were identified as potential improvements or edge cases. As they did not meet the confidence threshold for auto-fixing, please review them manually:")
            lines.append("")
            _findings_table(skipped_findings, lines, show_skipped=True)

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