---
sidebar_position: 2
title: Architecture
---

# Architecture

## How It Works

When a developer opens a PR against `main`, the pipeline automatically:

1. **Ingests** the diff — pulls only the changed Python (`.py`) and SQL (`.sql`) files.
2. **Reviews** the code in parallel across three specialized LLM passes: security, code quality, and performance.
3. **Refines** findings through PR-Agent (deduplication, filtering out low-value suggestions).
4. **Fixes** high-confidence issues automatically using Aider, on an isolated `agent/<branch>` — never touching the developer's own branch.
5. **Lints** the result natively with Ruff/SQLFluff in a retry loop until the branch is clean (or gives up gracefully after N attempts).
6. **Opens a new PR** with the fixes, tags the original author, and posts a summary comment linking back to it.

The developer keeps full control — they review and merge the *agent's* PR into their own branch whenever they're satisfied.

## Pipeline Diagram

![Pipeline Architecture](/img/pipeline-architecture.png)



**Key architectural decision:** everything runs *inside* the pipeline job — there is no 24/7 server, no webhook receiver, and no ngrok tunnel. The pipeline itself acts as the job queue: every PR gets its own ephemeral runner.

## Modular Architecture (Separation of Concerns)

To make the agent universal and adaptable to any team or tech stack, the architecture strictly separates the engine from the rules:

1. **The Engine (Agent Logic):** The underlying LangGraph orchestration, Aider execution, Git manipulation, and CI/CD integrations. This code is identical for every project and **never changes**.
2. **The Interface (Prompts):** The base template instructions that tell the AI *how* to act (e.g., "Output a JSON array", "Act as a ruthless reviewer").
3. **The Payload (Guidelines):** The team-specific rules (e.g., "Use TypeScript", "No mutable defaults"). These are provided by the user in a configuration file or markdown document. 

At runtime, the agent engine reads the base prompt template, injects the user's specific team guidelines, and executes the review. This means the agent can switch from reviewing Python/dbt to reviewing Node.js/Go simply by swapping the payload, without modifying a single line of backend code.

## Powered By (Under the Hood)

This pipeline stands on the shoulders of two incredible open-source agents:

1. **[Codium PR-Agent](https://github.com/Codium-ai/pr-agent):** Used dynamically in the `fetch_pr_agent_suggestions` node. Instead of writing custom logic to deduplicate, rank, and filter raw LLM findings, we pass the raw code analysis through PR-Agent's refinement engine to ensure only the highest-value insights are kept.
2. **[Aider](https://github.com/paulgauthier/aider):** Used in the `aider_llm_fix` node. Aider is the gold standard for AI pair programming. Rather than writing fragile string-replacement logic, the pipeline hands the refined PR-Agent findings over to Aider, which intelligently navigates the local checkout and applies the fixes natively.

## Repository Structure

```
.
├── ai-review.yml                     # Azure DevOps pipeline definition
├── cli.py                            # Entry point invoked by the pipeline
├── requirements.txt
├── .env.example                      # Template for local/dev config
├── scripts/
│   └── seed_rag.py                   # (optional) seeds guideline embeddings
├── src/
│   ├── agents/
│   │   ├── graph.py                  # LangGraph wiring
│   │   ├── state.py                  # Shared pipeline state (Pydantic model)
│   │   ├── utils/
│   │   │   ├── llm.py              # Bedrock invocation helper
│   │   │   └── guidelines.py       # Dynamic markdown loader
│   │   └── nodes/
│   │       ├── ingestion.py          # Pulls changed files + diffs from ADO
│   │       ├── code_quality.py       # LLM pass: bugs/style
│   │       ├── security_audit.py     # LLM pass: vulnerabilities
│   │       ├── performance.py        # LLM pass: bottlenecks
│   │       ├── fetch_pr_agent_suggestions.py  # Refines findings via PR-Agent
│   │       ├── aider_llm_fix.py      # Applies fixes on the agent branch
│   │       ├── aider_ci_fix.py       # Fixes CI/lint failures specifically
│   │       ├── create_agent_pr.py    # Opens the fix PR, comments on original
│   │       └── publish_review.py     # Posts the findings summary comment
│   ├── azure_client/
│   │   ├── auth.py                   # Token resolution (pipeline / PAT / SP)
│   │   ├── pr_client.py              # ADO REST wrappers (PRs, branches, comments)
│   │   └── ci_client.py              # ADO build/log wrappers
│   ├── guidelines/
│   │   ├── code_quality.md           # Dynamically loaded quality rules
│   │   ├── security.md               # Dynamically loaded security rules
│   │   └── performance.md            # Dynamically loaded performance rules
│   └── config/
│       └── settings.py               # pydantic-settings config object
└── tests/
```

## Node-by-Node Reference

| Node | File | Responsibility |
|---|---|---|
| `pr_ingestion` | `src/agents/nodes/ingestion.py` | Fetches changed files, raw content, and unified diffs from Azure DevOps |
| `code_quality` | `src/agents/nodes/code_quality.py` | LLM pass for bugs, logic errors, and style issues against a strict checklist |
| `security_audit` | `src/agents/nodes/security_audit.py` | LLM pass for vulnerabilities (SQLi, hardcoded secrets, insecure deserialization, etc.) |
| `performance_analysis` | `src/agents/nodes/performance.py` | LLM pass for N+1 queries, blocking I/O, unbounded caching, and similar bottlenecks |
| `fetch_pr_agent_suggestions` | `src/agents/nodes/fetch_pr_agent_suggestions.py` | Sends raw findings to PR-Agent for deduplication and refinement |
| `aider_llm_fix` | `src/agents/nodes/aider_llm_fix.py` | Creates the `agent/<branch>`, applies fixes file-by-file, runs the local lint loop |
| `create_agent_pr` | `src/agents/nodes/create_agent_pr.py` | Opens the fix PR against the developer's branch and comments back on the original PR |
| `publish_review` | `src/agents/nodes/publish_review.py` | Posts the findings summary table as a PR comment |

See [Getting Started](/docs/getting-started) for how to point this graph at your own repository, or [Customization](/docs/customization) to change what each node looks for.