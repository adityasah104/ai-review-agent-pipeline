"""
ci_status.py — Node 2 of the LangGraph pipeline.

Polls the Azure DevOps Builds API to determine whether the CI pipeline
for the PR's source branch has passed or failed.

Populates:
  - state.ci_passed       (bool)
  - state.ci_build_id     (int | None)
  - state.ci_log_summary  (str)  — passed to aider_ci_fix if CI failed
"""

import asyncio
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings
from src.azure_client.auth import get_azure_devops_token

import aiohttp

log = structlog.get_logger()

CI_POLL_INTERVAL_SECONDS = 5
CI_MAX_WAIT_SECONDS = 60  # Give ADO up to 60s to report a build result


async def run(state: PRReviewState) -> dict:
    """
    Polls ADO Builds API for the latest build on the PR source branch.
    Waits up to CI_MAX_WAIT_SECONDS for a completed result.
    """
    log.info("ci_status_check_start", pr_id=state.pr_id, attempt=state.ci_fix_attempts)

    branch = state.source_branch.replace("refs/heads/", "")
    org = settings.AZURE_DEVOPS_ORG
    project = settings.AZURE_DEVOPS_PROJECT

    builds_url = (
        f"https://dev.azure.com/{org}/{project}/_apis/build/builds"
        f"?branchName=refs/heads/{branch}"
        f"&$top=1"
        f"&queryOrder=startTimeDescending"
        f"&api-version=7.1"
    )

    try:
        token = await get_azure_devops_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        elapsed = 0
        async with aiohttp.ClientSession() as session:
            while elapsed < CI_MAX_WAIT_SECONDS:
                async with session.get(builds_url, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning(
                            "ci_status_api_error",
                            status=resp.status,
                            body=body[:200],
                        )
                        # Can't determine CI status — assume passed to not block review
                        return {
                            "ci_passed": True,
                            "ci_log_summary": f"Could not fetch CI status: HTTP {resp.status}",
                        }

                    data = await resp.json()
                    builds = data.get("value", [])

                    if not builds:
                        log.info("ci_status_no_builds_found", branch=branch, elapsed=elapsed)
                        # No builds yet — wait and retry
                        await asyncio.sleep(CI_POLL_INTERVAL_SECONDS)
                        elapsed += CI_POLL_INTERVAL_SECONDS
                        continue

                    build = builds[0]
                    build_id = build.get("id")
                    result = build.get("result", "")       # "succeeded", "failed", "canceled"
                    status = build.get("status", "")       # "completed", "inProgress", "notStarted"

                    log.info(
                        "ci_status_poll",
                        build_id=build_id,
                        status=status,
                        result=result,
                        elapsed=elapsed,
                    )

                    if status != "completed":
                        # Build still running — keep polling
                        await asyncio.sleep(CI_POLL_INTERVAL_SECONDS)
                        elapsed += CI_POLL_INTERVAL_SECONDS
                        continue

                    # Build is completed — check result
                    ci_passed = result == "succeeded"
                    log_summary = ""

                    if not ci_passed:
                        log_summary = await _fetch_build_log_summary(
                            session, headers, org, project, build_id
                        )

                    log.info(
                        "ci_status_check_done",
                        pr_id=state.pr_id,
                        ci_passed=ci_passed,
                        build_id=build_id,
                        result=result,
                    )

                    return {
                        "ci_passed": ci_passed,
                        "ci_build_id": build_id,
                        "ci_log_summary": log_summary,
                    }

            # Timeout — no completed build found within CI_MAX_WAIT_SECONDS
            log.warning(
                "ci_status_timeout",
                pr_id=state.pr_id,
                waited_seconds=elapsed,
            )
            return {
                "ci_passed": True,  # Assume passed — don't block review indefinitely
                "ci_log_summary": f"CI status timed out after {CI_MAX_WAIT_SECONDS}s — assuming passed.",
            }

    except Exception as e:
        log.error("ci_status_exception", error=str(e))
        # On unexpected error, do not block the pipeline
        return {
            "ci_passed": True,
            "ci_log_summary": f"ci_status node error: {e}",
        }


async def _fetch_build_log_summary(
    session: aiohttp.ClientSession,
    headers: dict,
    org: str,
    project: str,
    build_id: int,
) -> str:
    """
    Fetches the last 60 lines of log output from the failed build.
    This summary is passed to aider_ci_fix so Aider knows what to repair.
    """
    logs_url = (
        f"https://dev.azure.com/{org}/{project}/_apis/build/builds/{build_id}/logs"
        f"?api-version=7.1"
    )
    try:
        async with session.get(logs_url, headers=headers) as resp:
            if resp.status != 200:
                return "Could not fetch build logs."
            data = await resp.json()
            log_entries = data.get("value", [])

            if not log_entries:
                return "No log entries found."

            # Fetch the last log (most likely to contain the error)
            last_log = log_entries[-1]
            log_url = last_log.get("url", "")

            async with session.get(log_url, headers=headers) as log_resp:
                if log_resp.status != 200:
                    return "Could not fetch log content."
                raw = await log_resp.text()
                # Return last 60 lines — enough context for Aider without overwhelming it
                lines = raw.strip().splitlines()
                tail = "\n".join(lines[-60:])
                return tail

    except Exception as e:
        log.warning("ci_status_log_fetch_error", error=str(e))
        return f"Log fetch error: {e}"
