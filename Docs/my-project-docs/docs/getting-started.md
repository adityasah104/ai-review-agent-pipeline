---
sidebar_position: 1
title: Getting Started
---

# Getting Started

## Prerequisites

| Requirement | Notes |
|---|---|
| Azure DevOps project | With Git repos and Pipelines enabled |
| LLM Provider Access | API key or IAM role for AWS Bedrock, OpenAI, Anthropic, or any LiteLLM-supported provider. |
| Python 3.11 | Matches the pipeline's `UsePythonVersion@0` task |
| Pipeline permission to push/comment | See [Azure DevOps Setup](/docs/azure-devops) |

## Installation & Setup

We recommend testing the agent locally on your own machine before deploying it to your Azure DevOps pipeline. Here is the end-to-end setup for both environments.

---

### Option A: Local Setup (Testing on your machine)

**1. Clone the Review Agent**
Clone this agent repository onto your local machine:
```bash
git clone https://gitlab.com/adityasah104/ai-review-agent-pipeline.git
cd ai-review-agent-pipeline
```

**2. Set up a Virtual Environment & Install Dependencies**
The pipeline requires a specific, optimized fork of PR-Agent for its refinement node. Install it alongside the other requirements:
```bash
python3 -m venv .venv
source .venv/bin/activate

# Install the custom PR-Agent fork
pip install git+https://github.com/michaelv18k/pr-agent-latest-.git@feature/model-change

# Install the remaining pipeline dependencies (Aider, LangGraph, etc.)
pip install -r requirements.txt
```

**3. Configure your Environment Variables**
Copy the example config and point the agent to the local codebase you want it to review:
```bash
cp .env.example .env
```
Open `.env` and set `DEMO_REPO_PATH=/absolute/path/to/your/target/codebase` along with your LLM API keys.

**4. Run the Agent**
```bash
python cli.py
```
The agent will scan the target codebase, apply fixes, and output its logs to your terminal.

---

### Option B: Production Setup (Azure DevOps Pipeline)

Once you are comfortable with how the agent works, you can integrate it directly into your Azure DevOps PR process. 

**1. Commit the Pipeline File**
Copy the provided `ai-review.yml` file into the root of your target repository and push it to `main`. 
*Note: The YAML file already contains the exact `pip install` commands for the custom PR-Agent fork and dependencies.*

**2. Configure Secrets and Permissions**
Azure DevOps requires specific Variable Groups (for your API keys) and Branch Policies (to trigger on PRs). 

👉 **Continue to the full [Azure DevOps Setup Guide](/docs/azure-devops) for the step-by-step pipeline configuration.**