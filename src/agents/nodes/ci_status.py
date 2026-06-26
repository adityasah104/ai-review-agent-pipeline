import asyncio
import structlog
from src.agents.state import PRReviewState
from src.azure_client.ci_client import get_latest_build_for_branch, get_build_logs

log = structlog.get_logger()

# How long to wait for a CI build to appear (seconds)
CI_POLL_TIMEOUT = 120
CI_POLL_INTERVAL = 10


async def run(state: PRReviewState) -> dict:
    """
    Waits for the latest CI build on the source branch to complete.
    Returns ci_passed=True/False and the build log summary for Aider if failed.
    """
    log.info("ci_status_check_start", branch=state.source_branch)

    elapsed = 0
    build = None

    # Poll until we find a build for this branch or PR
    while elapsed < CI_POLL_TIMEOUT:
        build = await get_latest_build_for_branch(state.source_branch)
        if not build and state.pr_id:
            build = await get_latest_build_for_branch(f"refs/pull/{state.pr_id}/merge")
            
        if build:
            break
        log.info("ci_waiting_for_build", elapsed=elapsed)
        await asyncio.sleep(CI_POLL_INTERVAL)
        elapsed += CI_POLL_INTERVAL

    if not build:
        log.warning("ci_no_build_found", branch=state.source_branch)
        # If no CI pipeline is found, treat as passed and continue to review
        return {"ci_passed": True, "ci_build_id": None, "ci_log_summary": ""}

    build_id = build["id"]
    build_status = build.get("status", "")
    build_result = build.get("result", "")

    # If still in progress, wait for completion
    while build_status in ("inProgress", "notStarted", "postponed"):
        await asyncio.sleep(CI_POLL_INTERVAL)
        build = await get_latest_build_for_branch(state.source_branch)
        if not build and state.pr_id:
            build = await get_latest_build_for_branch(f"refs/pull/{state.pr_id}/merge")
        
        if build:
            build_status = build.get("status", "")
            build_result = build.get("result", "")

    ci_passed = build_result == "succeeded"
    log.info("ci_status_resolved", build_id=build_id, result=build_result)

    log_summary = ""
    if not ci_passed:
        # Fetch logs so Aider can understand what to fix
        full_logs = await get_build_logs(build_id)
        # Truncate to last 3000 chars — most relevant errors are at the end
        log_summary = full_logs[-3000:] if len(full_logs) > 3000 else full_logs

    return {
        "ci_passed": ci_passed,
        "ci_build_id": build_id,
        "ci_log_summary": log_summary,
    }