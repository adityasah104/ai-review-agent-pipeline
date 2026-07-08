import os
import asyncio
import subprocess
from src.agents.graph import graph

AI_AGENT_AUTHOR_NAME = "AI Review Agent"


async def main():
    pr_id = os.environ.get("SYSTEM_PULLREQUEST_PULLREQUESTID")
    if not pr_id:
        raise ValueError("Missing SYSTEM_PULLREQUEST_PULLREQUESTID.")

    # Prevent Infinite Loop Bug:
    # If the AI Agent just pushed a fix to this PR, ADO triggers a new pipeline.
    # We check the author of the actual source commit (not any Build.SourceVersion*
    # pipeline variable — those describe the synthetic PR merge commit, not the
    # real last commit on the source branch, and can never match here).
    #
    # This check must fail CLOSED, not open: if we can't determine the author,
    # we raise rather than silently proceeding, because "proceed when unsure"
    # is exactly what caused the original infinite loop. The pipeline's
    # `fetchDepth: 0` checkout guarantees this commit object is present locally,
    # so a failure here means something is genuinely wrong and needs attention.
    source_commit = os.environ.get("SYSTEM_PULLREQUEST_SOURCECOMMITID")
    if source_commit:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an", source_commit],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to look up commit author for {source_commit}. "
                f"Git error: {result.stderr.strip()}. "
                "Refusing to proceed rather than risk re-running on our own commit."
            )

        author = result.stdout.strip()
        if author == AI_AGENT_AUTHOR_NAME:
            print("\n" + "="*60)
            print("SAFEGUARD TRIGGERED: Infinite Loop Prevented")
            print("The latest commit on this PR was authored by the AI Review Agent.")
            print("Gracefully exiting so we don't infinitely review our own fixes!")
            print("="*60 + "\n")
            return

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
