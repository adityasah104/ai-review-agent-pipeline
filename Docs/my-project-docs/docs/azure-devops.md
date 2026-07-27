---
sidebar_position: 4
title: Azure DevOps Setup
---

# Azure DevOps Setup (Step-by-Step)

## 1. Create the Pipeline

1. Commit `ai-review.yml` to the root of your repository and push it.
2. In Azure DevOps: **Pipelines → Pipelines → New pipeline**.
3. Choose **Azure Repos Git**, select your repository.
4. Choose **Existing Azure Pipelines YAML file**, select the branch and path to `ai-review.yml`.
5. On the review screen, click the dropdown next to **Run** and choose **Save** (don't run yet — secrets aren't configured).

## 2. Set Up the Variable Group (Secrets)

1. **Pipelines → Library → + Variable group**.
2. Name it exactly `AI-Agent-Secrets` (must match the `- group:` reference in `ai-review.yml`).
3. Add each variable from the [Configuration Reference](/docs/configuration) that applies to your setup.
4. Click the **padlock icon** next to each secret value to mask it in logs.
5. Under **Pipeline permissions**, authorize the pipeline you created in Step 1.
6. **Save**.

## 3. Configure Branch Policy (Trigger on PR)

1. **Repos → Branches** → hover your target branch → **⋮ → Branch policies**.
2. Under **Build Validation**, click **+**.
3. Select the pipeline from Step 1, set **Trigger: Automatic**, **Policy requirement: Required**.
4. **Save**.

## 4. Grant Permission to Push Code & Comment

The pipeline authenticates using `$(System.AccessToken)`, which needs explicit repo permissions:

1. **Project settings → Repos → Repositories → [your repo] → Security**.
2. Find the identity named `[Project Name] Build Service ([Organization Name])`.
3. Set to **Allow**:
   - **Contribute** (push auto-fix commits)
   - **Contribute to pull requests** (post review comments)
   - **Create branch** (create the `agent/<branch>` fix branch)

## 5. (If Using AWS Keys Instead of an IAM Role)

Add `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` to the variable group from Step 2, scoped to an IAM policy that only allows `bedrock:InvokeModel` on the specific model ARN you're using.

## 6. Runner Pool Configuration

By default, the provided `ai-review.yml` is configured to run on standard, Microsoft-hosted Azure Pipeline VMs (`vmImage: 'ubuntu-latest'`). 

If you are developing or testing this on a free tier and have exhausted your free Microsoft-hosted parallel jobs, you may have configured a self-hosted pool (e.g., using your own PC/Mac as the runner). However, for enterprise customers and production deployments, **it is assumed you will use the standard Azure-hosted runner**. The pipeline is fully optimized for `ubuntu-latest` and handles all dependency installation natively on each run.

## Reference: `ai-review.yml`

```yaml
trigger: none
pr:
  branches:
    include:
      - main
  autoCancel: true

pool:
  vmImage: 'ubuntu-latest'

variables:
  - name: PIP_CACHE_DIR
    value: $(Pipeline.Workspace)/.cache/pip
  - name: AI_AGENT_GIT_NAME
    value: 'AI Review Agent'
  - name: AI_AGENT_GIT_EMAIL
    value: 'ai-agent@company.com'
  - group: AI-Agent-Secrets

resources:
  repositories:
    - repository: agent_repo
      type: github
      endpoint: MyGitHubConnection  # Replace with your GitHub Service Connection name
      name: adityasah104/ai-review-agent-pipeline
      ref: refs/heads/main

    - repository: michael_repo
      type: github
      endpoint: MyGitHubConnection  # Replace with your GitHub Service Connection name
      name: michaelv18k/pr-agent-latest-
      ref: refs/heads/feature/model-change

stages:
  - stage: AI_Review
    displayName: 'Code Quality Checks & AI Review'
    jobs:
      - job: AIReview
        displayName: 'AI Code Review & Auto-Fix'
        timeoutInMinutes: 15
        
        # Guard condition: Prevents the agent from re-running on its own commits
        condition: >
            and(
              succeededOrFailed(),
              eq(variables['Build.Reason'], 'PullRequest'),
              not(startsWith(variables['System.PullRequest.SourceBranch'], 'refs/heads/agent/'))
            )

        steps:
          - checkout: self
            persistCredentials: true
            fetchDepth: 0
            path: target_repo

          - checkout: agent_repo
            path: agent_repo

          - checkout: michael_repo
            path: michael_repo

          - task: UsePythonVersion@0
            inputs:
              versionSpec: '3.11'

          - script: |
              python -m pip install --upgrade pip
              
              # Force litellm version compatibility
              sed -i 's/litellm.*/litellm==1.81.10/g' $(Pipeline.Workspace)/michael_repo/requirements.txt
              
              # Install dependencies
              pip install -r $(Pipeline.Workspace)/agent_repo/requirements.txt
              pip install -r $(Pipeline.Workspace)/michael_repo/requirements.txt
              pip install --force-reinstall litellm==1.81.10
            displayName: 'Install dependencies'

          - script: |
              cd $(Pipeline.Workspace)/michael_repo
              mkdir -p pr_agent/settings
              cat <<EOF > pr_agent/settings/.secrets.toml
              [config]
              git_provider="azure"

              [azure_devops]
              pat="$(System.AccessToken)"
              org="${AZURE_DEVOPS_ORG}"
              EOF
            displayName: 'Configure PR-Agent Secrets'
            env:
              AZURE_DEVOPS_ORG: $(AZURE_DEVOPS_ORG)

          - script: |
              git config --local user.email "$(AI_AGENT_GIT_EMAIL)"
              git config --local user.name "$(AI_AGENT_GIT_NAME)"

              python $(Pipeline.Workspace)/agent_repo/cli.py
            displayName: 'Run AI Review & PR-Agent'
            workingDirectory: $(Pipeline.Workspace)/target_repo
            env:
              SYSTEM_ACCESSTOKEN: $(System.AccessToken)
              GROQ_API_KEY: $(GROQ_API_KEY)
              OPENAI_API_KEY: $(OPENAI_API_KEY)
              AWS_ACCESS_KEY_ID: $(AWS_ACCESS_KEY_ID)
              AWS_SECRET_ACCESS_KEY: $(AWS_SECRET_ACCESS_KEY)
              AWS_REGION: $(AWS_REGION)
              PYTHONPATH: $(Pipeline.Workspace)/michael_repo
              AZURE_DEVOPS_ORG: $(AZURE_DEVOPS_ORG)
              AZURE_DEVOPS_PROJECT: $(AZURE_DEVOPS_PROJECT)
              AZURE_DEVOPS_REPO: $(AZURE_DEVOPS_REPO)
              DEMO_REPO_PATH: "."
```

Continue to [Safety Mechanisms](/docs/safety) to understand how the pipeline avoids infinite loops and unsafe pushes.