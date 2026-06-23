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


def _build_comment(state: PRReviewState) -> str:
    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines.append("## AI Code Review")
    lines.append("")
    lines.append("> Automated review powered by **Amazon Bedrock Nova Pro**.")
    lines.append("")

    # ── CI Fix ────────────────────────────────────────────────────────────────
    if state.ci_fix_attempts > 0:
        lines.append("### CI Pipeline")
        if state.status == "CI_FIX_GAVE_UP":
            lines.append(
                f"> **Warning:** Attempted {state.ci_fix_attempts} automated fix(es) but "
                "the CI pipeline is still failing. Manual intervention is required."
            )
        else:
            lines.append(
                f"> Automated CI fix applied ({state.ci_fix_attempts} attempt(s)). "
                "All lint errors resolved."
            )
        lines.append("")

    # ── Findings ──────────────────────────────────────────────────────────────
    findings = state.findings
    if findings:
        total    = len(findings)
        critical = sum(1 for f in findings if f.get("severity") == "critical")
        major    = sum(1 for f in findings if f.get("severity") == "major")
        minor    = sum(1 for f in findings if f.get("severity") == "minor")

        lines.append("### Review Summary")
        lines.append("")
        lines.append("| Total | Critical | Major | Minor |")
        lines.append("|-------|----------|-------|-------|")
        lines.append(f"| {total} | {critical} | {major} | {minor} |")
        lines.append("")

        # Group by category
        by_category: dict = {}
        for f in findings:
            cat = f.get("category", "other")
            by_category.setdefault(cat, []).append(f)

        for cat, cat_findings in by_category.items():
            label = CATEGORY_LABEL.get(cat, cat.title())
            lines.append(f"### {label}")
            lines.append("")
            lines.append("| Severity | File | Location | Confidence | Finding |")
            lines.append("|----------|------|----------|------------|---------|")

            for f in cat_findings:
                severity  = f.get("severity", "minor")
                badge     = SEVERITY_BADGE.get(severity, severity.upper())
                file_path = f.get("file_path", "")
                line_hint = f.get("line_hint", "—")
                conf_val  = float(f.get("confidence", 0.0))
                conf_pct  = f"{int(conf_val * 100)}%"
                desc      = f.get("description", "").replace("|", "\\|")

                skipped = ""
                if conf_val < settings.MIN_FIX_CONFIDENCE:
                    skipped = " *(auto-fix skipped — low confidence)*"

                lines.append(
                    f"| {badge} | `{file_path}` | {line_hint} | {conf_pct} | {desc}{skipped} |"
                )

            lines.append("")

            # Suggestions as a block under each category table
            suggestions = [f for f in cat_findings if f.get("suggestion")]
            if suggestions:
                lines.append("**Suggestions**")
                lines.append("")
                for f in suggestions:
                    file_path = f.get("file_path", "")
                    line_hint = f.get("line_hint", "")
                    lines.append(
                        f"- **`{file_path}`** ({line_hint}): {f['suggestion']}"
                    )
                lines.append("")

    else:
        lines.append("### Review Summary")
        lines.append("")
        lines.append("No issues were identified in the changed code.")
        lines.append("")

    # ── Auto-Fix ──────────────────────────────────────────────────────────────
    if state.aider_fix_summary:
        lines.append("### Automated Fixes")
        lines.append("")
        lines.append(state.aider_fix_summary)
        lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append("---")
    lines.append(
        "*AI Review Agent &nbsp;·&nbsp; Amazon Bedrock Nova Pro &nbsp;·&nbsp; "
        "Findings are limited to lines changed in this PR.*"
    )

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