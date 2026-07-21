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

    lines.append("## 🤖 AI Code Review")
    lines.append("")
    author_tag = f"@<{state.pr_author_id}>" if state.pr_author_id else "@Author"
    lines.append(f"cc: {author_tag}")
    lines.append("")

    if state.status == "CI_FIX_GAVE_UP":
        lines.append("> **⚠️ Warning:** Attempted CI fixes but pipeline is still failing. Manual intervention required.")
        lines.append("")

    # Use refined findings if available, otherwise fallback to raw findings
    findings = state.refined_findings if state.refined_findings else state.findings

    high_confidence_findings = [f for f in findings if float(f.get("confidence", 0.0)) >= settings.MIN_FIX_CONFIDENCE]
    low_confidence_findings  = [f for f in findings if float(f.get("confidence", 0.0)) <  settings.MIN_FIX_CONFIDENCE]

    if high_confidence_findings:
        # Agent found and fixed real issues
        lines.append("### 🔧 Issues Found & Auto-Fixed")
        lines.append("")
        lines.append(
            f"The agent detected **{len(high_confidence_findings)} high-confidence issue(s)** and applied fixes on a separate agent branch. "
            "Please review the agent branch and merge it if the fixes look correct."
        )
        lines.append("")
        _findings_table(high_confidence_findings, lines)

        if low_confidence_findings:
            lines.append("---")
            lines.append("")
            lines.append("### ⚠️ Low-Confidence Findings — Needs Manual Review")
            lines.append("")
            lines.append(
                f"The following **{len(low_confidence_findings)} finding(s)** were flagged but **not auto-fixed** "
                f"because confidence was below the threshold (`{int(settings.MIN_FIX_CONFIDENCE * 100)}%`). "
                "Please review them manually:"
            )
            lines.append("")
            _findings_table(low_confidence_findings, lines)

    elif low_confidence_findings:
        # Clean on high-confidence but has lower-confidence flags
        lines.append("### ✅ Good to Go — No High-Confidence Issues Found")
        lines.append("")
        lines.append(
            "The agent reviewed this PR and found **no issues requiring an auto-fix**. "
            "You are good to merge!"
        )
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("### ⚠️ Low-Confidence Findings — Needs Manual Review")
        lines.append("")
        lines.append(
            f"However, the agent flagged **{len(low_confidence_findings)} lower-confidence finding(s)** "
            f"that were **not auto-fixed** (confidence below `{int(settings.MIN_FIX_CONFIDENCE * 100)}%`). "
            "These may or may not be real issues — please take a look before merging:"
        )
        lines.append("")
        _findings_table(low_confidence_findings, lines)

    else:
        # Completely clean
        lines.append("### ✅ Good to Go — No Issues Found")
        lines.append("")
        lines.append(
            "The agent reviewed the changes in this PR and found **no issues**. "
            "No auto-fixes were needed. You are good to merge!"
        )
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