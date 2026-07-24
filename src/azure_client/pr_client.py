import httpx
from typing import List, Dict, Optional
from src.config.settings import settings
from src.azure_client.auth import get_auth_headers
def _base_url() -> str:
    return (
        f"https://dev.azure.com/{settings.AZURE_DEVOPS_ORG}/"
        f"{settings.AZURE_DEVOPS_PROJECT}/_apis"
    )

async def get_pr_diff(repository_id: str, pr_id: int) -> List[Dict]:
    """
    Fetches the list of changed files (iterations/changes) for a PR.
    Returns a list of dicts with file path and change type.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await get_auth_headers()
        # Get latest iteration ID
        iter_resp = await client.get(
            f"{_base_url()}/git/repositories/{repository_id}/pullRequests/{pr_id}/iterations",
            headers=headers,
            params={"api-version": "7.1"},
        )
        iter_resp.raise_for_status()
        iterations = iter_resp.json().get("value", [])
        if not iterations:
            return []

        latest_iter_id = iterations[-1]["id"]

        # Get changes in latest iteration
        changes_resp = await client.get(
            f"{_base_url()}/git/repositories/{repository_id}/pullRequests/{pr_id}"
            f"/iterations/{latest_iter_id}/changes",
            headers=headers,
            params={"api-version": "7.1"},
        )
        changes_resp.raise_for_status()
        return changes_resp.json().get("changeEntries", [])


async def get_file_content(repository_id: str, file_path: str, branch: str) -> Optional[str]:
    """Fetches raw file content from a branch."""
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await get_auth_headers()
        resp = await client.get(
            f"{_base_url()}/git/repositories/{repository_id}/items",
            headers=headers,
            params={
                "path": file_path,
                "versionDescriptor.version": branch,
                "versionDescriptor.versionType": "branch",
                "$format": "text",
                "api-version": "7.1",
            },
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text


async def post_pr_comment(repository_id: str, pr_id: int, comment_text: str) -> Dict:
    """Posts a top-level comment (thread) to a PR."""
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await get_auth_headers()
        resp = await client.post(
            f"{_base_url()}/git/repositories/{repository_id}/pullRequests/{pr_id}/threads",
            headers=headers,
            params={"api-version": "7.1"},
            json={
                "comments": [
                    {
                        "parentCommentId": 0,
                        "content": comment_text,
                        "commentType": 1,
                    }
                ],
                "status": "active",
            },
        )
        resp.raise_for_status()
        return resp.json()
    
    #Multi-branch Approach
    
async def get_pr_metadata(repository_id: str, pr_id: int) -> Dict:
    """Fetches full PR metadata including the createdBy field (author)."""
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await get_auth_headers()
        resp = await client.get(
            f"{_base_url()}/git/repositories/{repository_id}/pullRequests/{pr_id}",
            headers=headers,
            params={"api-version": "7.1"},
        )
        resp.raise_for_status()
        return resp.json()


async def create_branch(repository_id: str, new_branch: str, base_branch: str) -> bool:
    """
    Creates a new branch in ADO from the tip of base_branch.
    ADO branch creation uses the refs/update API.
    We need the current objectId (commit SHA) of base_branch as starting point.
    Returns True on success.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await get_auth_headers()

        # Step 1: Get current commit SHA of base_branch
        refs_resp = await client.get(
            f"{_base_url()}/git/repositories/{repository_id}/refs",
            headers=headers,
            params={"filter": f"heads/{base_branch}", "api-version": "7.1"},
        )
        refs_resp.raise_for_status()
        refs = refs_resp.json().get("value", [])
        if not refs:
            raise ValueError(f"Base branch '{base_branch}' not found in ADO")
        base_object_id = refs[0]["objectId"]

        # Step 2: Create the new branch pointing at that commit
        create_resp = await client.post(
            f"{_base_url()}/git/repositories/{repository_id}/refs",
            headers=headers,
            params={"api-version": "7.1"},
            json=[
                {
                    "name": f"refs/heads/{new_branch}",
                    "oldObjectId": "0000000000000000000000000000000000000000",
                    "newObjectId": base_object_id,
                }
            ],
        )
        create_resp.raise_for_status()
        result = create_resp.json().get("value", [{}])[0]
        return result.get("success", False)


async def create_pull_request(
    repository_id: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
    reviewer_ids: Optional[List[str]] = None,
) -> Dict:
    """
    Creates a Pull Request in ADO from source_branch to target_branch.
    reviewer_ids is a list of ADO UUIDs.
    Returns the full PR response JSON (contains pullRequestId, etc.)
    """
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await get_auth_headers()
        # ADO resolves reviewers by UUID using the 'id' field
        reviewers = [{"id": rid} for rid in (reviewer_ids or []) if rid]
        body = {
            "title": title,
            "description": description,
            "sourceRefName": f"refs/heads/{source_branch}",
            "targetRefName": f"refs/heads/{target_branch}",
            "reviewers": reviewers,
        }
        resp = await client.post(
            f"{_base_url()}/git/repositories/{repository_id}/pullRequests",
            headers=headers,
            params={"api-version": "7.1"},
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
async def get_existing_pull_request(repository_id: str, source_branch: str, target_branch: str) -> Optional[Dict]:
    """Finds an existing active PR between source_branch and target_branch."""
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await get_auth_headers()
        resp = await client.get(
            f"{_base_url()}/git/repositories/{repository_id}/pullRequests",
            headers=headers,
            params={
                "searchCriteria.sourceRefName": f"refs/heads/{source_branch}",
                "searchCriteria.targetRefName": f"refs/heads/{target_branch}",
                "searchCriteria.status": "active",
                "api-version": "7.1",
            },
        )
        if resp.status_code == 200:
            prs = resp.json().get("value", [])
            if prs:
                return prs[0]
        return None
