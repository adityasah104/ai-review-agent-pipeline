import os
from src.agents.graph import builder

if __name__ == "__main__":
    pr_id = os.environ.get("SYSTEM_PULLREQUEST_PULLREQUESTID")
    if not pr_id:
        raise ValueError("Missing SYSTEM_PULLREQUEST_PULLREQUESTID.")
        
    state = {"pr_id": int(pr_id), "status": "PENDING"}
    builder.invoke(state)