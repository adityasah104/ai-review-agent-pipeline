import subprocess
import structlog
from src.agents.state import PRReviewState
from src.azure_client.pr_client import get_pr_diff, get_file_content, get_pr_metadata
from src.config.settings import settings
from src.azure_client.auth import get_azure_devops_token

log = structlog.get_logger()


async def run(state: PRReviewState) -> dict:
    """
    Fetches the list of changed files and their content from the PR.
    Only fetches Python (.py) and SQL (.sql) files — skips everything else.
    Also computes a unified git diff for each file so LLM agents review
    only the changed lines, not the entire file.
    Also fetches the PR author's ADO uniqueName for @mention.
    """
    log.info("ingestion_start", pr_id=state.pr_id)

    try:
        changes = await get_pr_diff(state.repository_id, state.pr_id)

        # Fetch PR author for @mention on the agent PR
        pr_author_id = ""
        try:
            pr_meta = await get_pr_metadata(state.repository_id, state.pr_id)
            pr_author_id = pr_meta.get("createdBy", {}).get("id", "")
            log.info("ingestion_pr_author", author=pr_author_id)
        except Exception as e:
            log.warning("ingestion_pr_author_failed", error=str(e))

        changed_files = []
        file_contents = {}

        for change in changes:
            item = change.get("item", {})
            path = item.get("path", "")
            change_type = change.get("changeType", "")

            # Only care about Python and SQL files
            if not (path.endswith(".py") or path.endswith(".sql")):
                continue

            # Skip deleted files
            if "delete" in change_type.lower():
                continue

            # Skip vector DB/chroma directories
            if "chroma_db" in path.lower() or "chroma" in path.lower():
                continue

            changed_files.append({
                "path": path,
                "change_type": change_type,
                "file_type": "python" if path.endswith(".py") else "sql",
            })

            # Fetch actual content from the source branch (needed by Aider)
            content = await get_file_content(
                state.repository_id,
                path,
                state.source_branch.replace("refs/heads/", ""),
            )
            if content:
                file_contents[path] = content

        # ------------------------------------------------------------------
        # Compute unified diffs for each changed file using the local clone.
        # This is what the LLM review agents will use — focused on only the
        # lines the developer actually changed.
        # Falls back silently: if this fails, agents use full file_contents.
        # ------------------------------------------------------------------
        file_diffs = {}
        repo_path = settings.DEMO_REPO_PATH
        branch = state.source_branch.replace("refs/heads/", "")

        try:
            # Fetch latest remote refs so the diff is accurate
            token = await get_azure_devops_token()
            subprocess.run(
                ["git", "-c", f"http.extraheader=AUTHORIZATION: bearer {token}", "fetch", "origin"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            for file_meta in changed_files:
                rel_path = file_meta["path"].lstrip("/")
                diff_result = subprocess.run(
                    ["git", "diff", f"origin/main...origin/{branch}", "--", rel_path],
                    cwd=repo_path, capture_output=True, text=True, timeout=15,
                )
                if diff_result.returncode == 0 and diff_result.stdout.strip():
                    file_diffs[file_meta["path"]] = diff_result.stdout
            log.info("diff_computed", files_with_diff=len(file_diffs))
        except Exception as e:
            log.warning("diff_computation_failed", error=str(e))
            # file_diffs stays empty — agents will fall back to full content

        log.info("ingestion_done", files_found=len(changed_files))
        return {
            "changed_files": changed_files,
            "file_contents": file_contents,
            "file_diffs": file_diffs,
            "pr_author_id": pr_author_id,
            "status": "INGESTED",
        }

    except Exception as e:
        log.error("ingestion_failed", error=str(e))
        return {"status": "FAILED", "error": f"Ingestion failed: {e}"}
