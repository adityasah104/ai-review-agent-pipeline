import os
import asyncio
from src.agents.graph import graph

async def main():
    pr_id = os.environ.get("SYSTEM_PULLREQUEST_PULLREQUESTID")
    if not pr_id:
        raise ValueError("Missing SYSTEM_PULLREQUEST_PULLREQUESTID.")
        
    state = {
        "job_id": int(os.environ.get("BUILD_BUILDID", "0")),
        "pr_id": int(pr_id),
        "repository_id": os.environ.get("AZURE_DEVOPS_REPO", "demo-project"),
        "project": os.environ.get("AZURE_DEVOPS_PROJECT", "demo-project"),
        "source_branch": os.environ.get("SYSTEM_PULLREQUEST_SOURCEBRANCH", ""),
        "target_branch": os.environ.get("SYSTEM_PULLREQUEST_TARGETBRANCH", ""),
        "status": "PENDING"
    }
    
    await graph.ainvoke(state)

if __name__ == "__main__":
    asyncio.run(main())
