# Implementation Plan: Migrating AI Review Agent to Azure DevOps Pipelines

Moving this system from a local machine/FastAPI server to a native Azure DevOps Pipeline is the best choice for production. It eliminates the need to host a 24/7 server, removes the dependency on ngrok, and naturally scales by spinning up a new pipeline worker for every Pull Request.

Here is the step-by-step implementation plan, including my architectural views on the necessary changes.

---

## 1. Architectural Shifts (What changes?)

### A. Webhooks ➔ Pipeline Triggers
- **Current:** Azure DevOps sends a webhook to your local FastAPI server.
- **Future:** Azure DevOps natively triggers `azure-pipelines.yml` when a PR is created or updated. We will delete `main.py`, `routes.py`, and `signature.py`.

### B. SQLite Queue ➔ Native Pipeline Isolation
- **Current:** The local server uses SQLite (`ReviewJob`) and a background worker to queue multiple PRs.
- **Future:** The Azure DevOps pipeline *is* the queue. Each PR gets its own isolated, ephemeral VM runner. We can completely remove the SQLite database dependency.

### C. Networking & PR-Agent Integration (Huge Win!)
- **Current:** Your agent POSTs to PR-Agent over the internet via Ngrok, and then your FastAPI server listens for an HTTP POST back.
- **Future:** Since **both agents will run in the same pipeline**, we no longer need Webhooks, Ngrok, or public internet routing! We can integrate directly on the runner.
- **Solution:** We have two options for the new integration:
  1. **Direct Python Import:** If PR-Agent is a Python package, we just `import pr_agent` and pass the findings in-memory.
  2. **Localhost API:** We can spin up PR-Agent's server in the background of the pipeline step (`python run_pr_agent.py &`), and your agent can just POST directly to `http://localhost:8080/submit` and wait synchronously for the response. No public IP needed!

### D. Authentication
- **Current:** You use a Service Principal OAuth flow via `auth.py` to push code.
- **Future:** We can simplify this! ADO pipelines provide a native `$(System.AccessToken)` which grants scripts direct permission to push to the branch and post PR comments without needing external Service Principals.

---

## 2. Codebase Refactoring Plan

To run in a pipeline, the agent needs to become a **CLI tool** rather than a web server.

### Phase 1: Create `cli.py`
We will create a new entry point that accepts the PR ID directly from the pipeline environment variables and kicks off the LangGraph workflow:
```python
import os
import argparse
from src.agents.graph import builder

def main():
    pr_id = os.environ.get("SYSTEM_PULLREQUEST_PULLREQUESTID")
    if not pr_id:
        print("Not running in a PR context.")
        return
        
    state = {"pr_id": int(pr_id), "status": "PENDING"}
    builder.invoke(state)

if __name__ == "__main__":
    main()
```

### Phase 2: Rip out FastAPI & SQLite
Delete the following files to strip the system down to purely the LangGraph intelligence:
- `src/gateway/` (routes, signature)
- `src/db/` (database, models)
- `src/queue/` (worker)
- `main.py`

### Phase 3: Modify Graph Nodes
- **`ci_status.py`**: We can remove this entirely! In a pipeline, the agent step will only run *after* the CI linting step. We can use native YAML conditions (`condition: failed()`) to decide if we need to run the `aider_ci_fix` node.
- **`fetch_pr_agent_suggestions.py`**: Rewrite this to call PR-Agent locally (either via a Python function call, a local CLI subprocess, or a synchronous request to `localhost` if PR-Agent boots up its own server in the pipeline).

---

## 3. Azure DevOps Pipeline YAML (`ai-review.yml`)

We will add a pipeline configuration to the root of the repository. It will look like this:

```yaml
trigger: none
pr:
  branches:
    include:
      - main

pool:
  vmImage: 'ubuntu-latest'

variables:
  # Secrets will be mapped from Azure DevOps Library (Variable Groups)
  - group: AI-Agent-Secrets

steps:
  - checkout: self
    persistCredentials: true # Allows Aider to git push back to the branch

  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.11'

  - script: |
      pip install -r requirements.txt
    displayName: 'Install Agent Dependencies'

  # 1. Native CI Checking
  - script: |
      ruff check src/
      sqlfluff lint models/ --dialect ansi
    displayName: 'Standard CI Checks'
    continueOnError: true

  # 2. AI Review Agent & PR-Agent integration
  - script: |
      # (Optional) Spin up Michael's PR-Agent locally in the background
      # python -m pr_agent.server &
      
      # Configure Git for Aider commits
      git config --global user.email "ai-agent@company.com"
      git config --global user.name "AI Review Agent"
      
      # Run the agent CLI
      python cli.py
    displayName: 'Run AI Review & PR-Agent Auto-Fix'
    env:
      SYSTEM_ACCESSTOKEN: $(System.AccessToken)
      AWS_ACCESS_KEY_ID: $(AWS_ACCESS_KEY_ID)
      AWS_SECRET_ACCESS_KEY: $(AWS_SECRET_ACCESS_KEY)
      PR_AGENT_REFINE_URL: "http://localhost:8080/submit" # Pointing locally!
```

---

## 4. My Views & Recommendations

1. **Perfect Timing:** This is exactly the right time to do this. The logic is stable, the AI fixes are accurate, and moving to a pipeline will instantly solve all "Server Uptime" and "Concurrent PR" scaling issues.
2. **Talk to Michael ASAP:** You and Michael need to agree on exactly *how* his agent boots up inside the pipeline. Does he compile it to a Docker container? Is it a Python wheel? Once his agent is running on the pipeline runner, we just point `PR_AGENT_REFINE_URL` to `localhost` and the entire networking problem disappears.
3. **Cost Optimisation:** Because ADO pipelines charge by the minute, executing both AI agents on the same pipeline runner is incredibly cost-efficient compared to hosting two separate 24/7 VMs in Azure.

---

## 5. Technical Step-by-Step Checklist

Here is the exact checklist to execute this migration today:

### Step 1: Create the new CLI Entrypoint
1. In the root of `ai-review-agent`, create a new file named `cli.py`.
2. Add the code to read the PR ID from the pipeline environment variables:
   ```python
   import os
   from src.agents.graph import builder

   if __name__ == "__main__":
       pr_id = os.environ.get("SYSTEM_PULLREQUEST_PULLREQUESTID")
       if not pr_id:
           raise ValueError("Missing SYSTEM_PULLREQUEST_PULLREQUESTID.")
           
       state = {"pr_id": int(pr_id), "status": "PENDING"}
       builder.invoke(state)
   ```

### Step 2: Delete the Web Server & Queue Files
Since we are no longer running a 24/7 web server, permanently delete:
- `main.py`
- `src/gateway/` (the entire folder containing `routes.py` and `signature.py`)
- `src/db/` (the entire folder containing SQLite database setup)
- `src/queue/` (the entire folder containing the background worker)

### Step 3: Refactor the PR-Agent Integration Node
1. Open `src/agents/nodes/fetch_pr_agent_suggestions.py`.
2. Remove all logic that saves state to SQLite or waits for a webhook.
3. Replace it with a direct synchronous HTTP request to PR-Agent running locally:
   ```python
   import httpx
   
   def fetch_pr_agent_suggestions_node(state):
       # Send findings to PR-Agent (running in background on same VM)
       response = httpx.post("http://localhost:8080/api/pr-agent/submit", json=payload, timeout=300)
       
       # Immediately read the refined findings
       state["refined_findings"] = response.json().get("refined_findings", [])
       return {"refined_findings": state["refined_findings"]}
   ```

### Step 4: Remove the `ci_status` Node
Because Azure DevOps automatically runs CI checks *before* your agent script, your agent doesn't need to poll ADO anymore! 
1. Open `src/agents/graph.py`.
2. Delete the `ci_status` node.
3. Update the graph edges to jump straight into the AI review.

### Step 5: Configure Azure DevOps (Detailed UI Steps)
To set this up using the latest Azure DevOps (ADO) UI, follow these explicit steps:

#### 5.1 Create the Pipeline
1. In your local repo, create `azure-pipelines.yml` (or `ai-review.yml`) using the template from Section 3, commit, and push it to Azure DevOps.
2. In your Azure DevOps project, navigate to **Pipelines** > **Pipelines** on the left sidebar.
3. Click the **New pipeline** button (top right).
4. **Where is your code?**: Select **Azure Repos Git** (or GitHub/Bitbucket, depending on where your code lives).
5. **Select a repository**: Choose your repository.
6. **Configure your pipeline**: Choose **Existing Azure Pipelines YAML file**.
7. Select your branch (e.g., `main`) and the path to your YAML file.
8. Click **Continue**. On the review screen, click the dropdown arrow next to "Run" and select **Save** (do not run it yet, as we need to set up secrets).

#### 5.2 Set up the Variable Group (Secrets)
1. Navigate to **Pipelines** > **Library** on the left sidebar.
2. Click **+ Variable group**.
3. **Properties**: Name it exactly `AI-Agent-Secrets` (this matches the YAML `- group: AI-Agent-Secrets`).
4. **Variables**: Click **+ Add** to add your secrets. Add keys like `GROQ_API_KEY`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`.
   - *CRITICAL:* Click the **padlock icon** next to the value field to lock them as secrets so they are masked in logs.
5. **Pipeline permissions**: Go to the "Pipeline permissions" tab at the top of the variable group, click **+** and explicitly authorize your newly created pipeline to access these secrets.
6. Click **Save**.

#### 5.3 Configure Branch Policies (Trigger on PR)
1. Navigate to **Repos** > **Branches** on the left sidebar.
2. Hover over your target branch (e.g., `main`), click the **More options** (three dots) icon, and select **Branch policies**.
3. Scroll down to **Build Validation** and click the **+** button.
4. **Build pipeline**: Select the pipeline you created in Step 5.1.
5. **Trigger**: Select **Automatic** (whenever the source branch is updated).
6. **Policy requirement**: Select **Required** (this blocks merging until the AI reviews it).
7. Click **Save**.

#### 5.4 Grant Permission to Push Code & Comment
Since the pipeline uses `$(System.AccessToken)` to commit Aider fixes and leave PR comments, the pipeline's build service identity needs explicit repository permissions:
1. Go to **Project settings** (gear icon in the bottom left corner).
2. Under the **Repos** section, select **Repositories**.
3. Select your repository, then click the **Security** tab.
4. Under "Users", search for your pipeline identity. It is usually named `[Project Name] Build Service ([Organization Name])`.
5. Ensure the following permissions are set to **Allow**:
   - **Contribute** (allows pushing code for auto-fixes)
   - **Contribute to pull requests** (allows adding AI review comments to the PR)
   - **Create branch** (if Aider creates a new branch for the fix)
