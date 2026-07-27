<div align="center">

# 🤖 AI PR Review & Auto-Fix Agent

**An autonomous, end-to-end Pull Request Review & Auto-Fix pipeline for Azure DevOps.**
It doesn't just leave comments — it checks out the code, writes the fixes itself, runs a self-healing lint/CI loop, and opens a ready-to-merge branch before a human ever looks at it.

`Azure DevOps Pipelines` · `LangGraph` · `Amazon Bedrock (Nova Pro)` · `Aider` · `Ruff` · `SQLFluff` · `PR-Agent`

[**📖 Full Documentation**](https://your-org.github.io/your-repo/) · [**🚀 Getting Started**](https://your-org.github.io/your-repo/docs/getting-started) · [**🗺️ Roadmap**](https://your-org.github.io/your-repo/roadmap) · [**🐛 Issues**](https://github.com/your-org/your-repo/issues)

</div>

---

## ✨ Features

| | |
|---|---|
| 🔍 **Multi-Angle Automated Review** | Three specialized LLM passes run in parallel on every PR — **security**, **code quality**, and **performance** — each constrained to a strict, checklist-driven scope to avoid noisy or hallucinated findings. |
| 🛠️ **True Auto-Fix, Not Just Comments** | Checks out the code, applies fixes with Aider, and pushes a working branch — no copy-pasting suggestions or manually resolving formatting after the fact. |
| 🧵 **Self-Healing CI Loop** | Runs native linters (Ruff, SQLFluff) after every fix, feeds any remaining errors back to the model, and retries — bounded and guaranteed to terminate. |
| 🌿 **Branch-Safe by Design** | Fixes always land on an isolated `agent/<branch>`, never on the developer's own branch. The developer reviews and merges the agent's PR on their own terms. |
| 🔁 **Infinite-Loop Protection** | Detects and skips runs triggered by the agent's own commits, with a fail-closed design — if it can't verify authorship, it stops rather than guessing. |
| 🎯 **Confidence-Gated Auto-Fixing** | Every finding carries a confidence score; only fixes above your configured threshold are applied automatically, everything else is surfaced for manual review. |
| 🧩 **Model-Agnostic & Language-Agnostic** | Swap the Bedrock model, linters, or file-type filters to fit any language or stack — the fix/validate/retry pattern is fully reusable. |
| 🚫 **No Servers, No Webhooks, No Tunnels** | Runs entirely inside the Azure DevOps pipeline job. No 24/7 host, no ngrok, no SQLite queue — the pipeline *is* the queue. |
| 📝 **Actionable PR Summaries** | Posts a clean, tabular summary comment on the original PR — severity, file, line, confidence, and issue — plus a direct link to the agent's fix PR. |
| 🔐 **Native ADO Auth** | Uses the pipeline's built-in `$(System.AccessToken)` by default, with Service Principal or PAT fallback — no extra secrets to manage for basic setups. |

---

## How It Works

```
PR opened → Native CI checks → LangGraph review (security · quality · performance)
          → PR-Agent refinement → Aider auto-fix on agent/<branch> → local lint loop
          → Agent PR opened → Summary comment posted on the original PR
```

Full architecture diagram, node-by-node breakdown, and repository structure →
**[Architecture Docs](https://your-org.github.io/your-repo/docs/architecture)**

---

## Quickstart

```bash
# 1. Copy the agent into your repo
cp cli.py requirements.txt ai-review.yml -r src/ /path/to/your-repo/

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env   # fill in your values

# 4. Wire up the Azure DevOps pipeline (branch policy + secrets)
```

Full prerequisites, install steps, and language-generalization guide →
**[Getting Started Docs](https://your-org.github.io/your-repo/docs/getting-started)**

---

## Documentation

| Topic | Link |
|---|---|
| 🚀 Getting Started — prerequisites, install, generalizing to any repo | [Docs →](https://your-org.github.io/your-repo/docs/getting-started) |
| 🏗️ Architecture — pipeline diagram, node reference, repo structure | [Docs →](https://your-org.github.io/your-repo/docs/architecture) |
| ⚙️ Configuration — full environment variable reference | [Docs →](https://your-org.github.io/your-repo/docs/configuration) |
| ☁️ Azure DevOps Setup — step-by-step pipeline, secrets, branch policy | [Docs →](https://your-org.github.io/your-repo/docs/azure-devops) |
| 🎛️ Customization — checklists, thresholds, swapping linters/languages | [Docs →](https://your-org.github.io/your-repo/docs/customization) |
| 🛡️ Safety Mechanisms — loop protection, validation gates, bounded retries | [Docs →](https://your-org.github.io/your-repo/docs/safety) |
| ⚠️ Known Limitations — truncation risk, tool comparison | [Docs →](https://your-org.github.io/your-repo/docs/limitations) |
| 🧯 Troubleshooting — symptom/cause/fix table, diagnostic checklist | [Docs →](https://your-org.github.io/your-repo/docs/troubleshooting) |
| 🗺️ Roadmap — planned improvements | [Docs →](https://your-org.github.io/your-repo/roadmap) |

---


<div align="center">

**[📖 Full Documentation](https://your-org.github.io/your-repo/)** · Built with LangGraph, Amazon Bedrock, and Aider

</div>