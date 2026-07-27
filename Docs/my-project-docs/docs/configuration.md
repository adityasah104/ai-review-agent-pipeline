---
sidebar_position: 3
title: Configuration Reference
---

# Configuration Reference

All configuration is read via `pydantic-settings` from environment variables.

| Variable | Required | Description |
|---|---|---|
| `AZURE_DEVOPS_ORG` | ✅ | Your ADO organization name (from `dev.azure.com/<org>`) |
| `AZURE_DEVOPS_PROJECT` | ✅ | Project name inside ADO |
| `AZURE_DEVOPS_REPO` | ✅ | Repository name |
| `AZURE_DEVOPS_PAT` | Fallback | Personal Access Token, only used if `SYSTEM_ACCESSTOKEN` / Service Principal auth is unavailable |
| `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | Optional | Service Principal credentials, if not relying on the pipeline's native OAuth token |
| `AZURE_DEVOPS_WEBHOOK_SECRET` | Legacy | Only relevant if you still run the old webhook-based server; unused in the pipeline-native flow |
| `LLM_MODEL_ID` | ✅ | The model identifier (e.g., `bedrock/amazon.nova-pro-v1:0`, `gpt-4o`, `claude-3-5-sonnet-20240620`) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Optional | Provide the respective API key if using OpenAI or Anthropic models |
| `AWS_REGION` | Optional | Required only if using AWS Bedrock |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Optional | Leave blank to use an IAM role attached to the runner if using Bedrock |
| `DEMO_REPO_PATH` | ✅ | Absolute path to the local checkout Aider will edit |
| `AIDER_MAX_CI_RETRIES` | ✅ | Max retry attempts for the CI-fix loop (default `2`) |
| `MIN_FIX_CONFIDENCE` | ✅ | Confidence threshold (0.0–1.0) below which findings are reported but not auto-fixed (default `0.85`) |
| `PR_AGENT_REFINE_URL` | Optional | Localhost endpoint if PR-Agent is run as a background server rather than imported directly |
| `CHROMA_DB_PATH` | Optional | Only needed if using the RAG guideline indexer (`scripts/seed_rag.py`) |

> ⚠️ Never commit real values for any of these — use the ADO Variable Group's padlock icon to mark secrets as masked.