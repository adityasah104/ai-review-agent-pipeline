---
sidebar_position: 9
title: Problems Faced & Solutions
---

# Problems Faced & Engineering Decisions

Building an autonomous agent that directly edits and pushes code to production repositories requires extreme safety guardrails. During the development of this pipeline, several complex challenges arose. 

This page documents those issues and the architectural decisions made to solve them, which may help you if you encounter similar edge cases in your own environment.

## 1. Exhausting Azure DevOps Free-Tier Constraints
**The Problem:** Azure DevOps provides a limited number of free parallel jobs (usually 1,800 minutes/month) for Microsoft-hosted agents. During heavy testing and rapid iteration, we exhausted this free tier, which caused pipelines to queue indefinitely without running.

**The Solution:** We temporarily configured a **Self-Hosted Pool** by registering a local development machine (an Apple Silicon Mac) as an ADO pipeline runner. This allowed unlimited, free testing without relying on Microsoft's servers. 

**Takeaway for Customers:** If you are an enterprise customer with paid ADO capacity, you should simply use `vmImage: 'ubuntu-latest'` to leverage Microsoft's scalable infrastructure. If you are a solo developer or startup that runs out of free minutes, you can easily pivot the YAML to use a `pool: { name: 'Default' }` and run the agent locally on your own hardware for free.

## 2. The Infinite Pipeline Loop
**The Problem:** Because the agent automatically pushes code fixes to a pull request, that push event would re-trigger the Azure DevOps PR pipeline. This caused the agent to review its own fixes, push another commit, and trigger itself infinitely (at one point causing a 63-run loop). 

**The Solution:** We implemented a two-stage **Loop Guard**. 
1. In the `azure-pipelines.yml`, we explicitly excluded branches starting with `refs/heads/agent/`.
2. Because ADO's native variables sometimes track the *merge commit* rather than the *source commit*, we built a manual check into `cli.py`. The agent inspects the actual `SYSTEM_PULLREQUEST_SOURCECOMMITID`. If the author of that commit matches the agent's configured Git email, the agent gracefully exits before spinning up any LLM calls.

## 3. LLM Hallucinations & Subjective Linting
**The Problem:** Early iterations of the agent would flag highly subjective style choices, complain about formatting, or hallucinate "vulnerabilities" that didn't exist, leading to noisy PRs and frustrated developers.

**The Solution:** We stripped all formatting responsibilities away from the LLM and gave them back to native linters (`ruff` and `sqlfluff`). For logic and bugs, we introduced **Strict Checklists** injected into the prompt. The LLM is strictly constrained to only flag issues present on that list. Additionally, we use **Codium PR-Agent** as a refinement layer to deduplicate and filter out low-value suggestions before they ever reach the Auto-Fix stage.

## 4. Unreliable Code Rewrites & Truncation
**The Problem:** Asking the LLM to output surgically precise Git diff blocks (search/replace) often failed on large files, corrupting the code syntax.

**The Solution:** We switched Aider to use `--edit-format whole`. The model rewrites the entire file in one go. To counter truncation risks on massive files, we implemented a **Syntax-Validity Floor**. If the LLM's output fails a native parse check (`ast.parse` for Python, `sqlfluff parse` for SQL), the agent automatically reverts the file with `git checkout -- <file>` and falls back to simply leaving a comment.

## 5. Over-Confident Bad Fixes
**The Problem:** Sometimes the LLM correctly identified a bug, but its generated fix actually broke the logic or introduced new syntax errors.

**The Solution:** We implemented a **Confidence-Gated Auto-Fixing** mechanism (`MIN_FIX_CONFIDENCE = 0.85`). Only findings with a mathematically high confidence score are passed to Aider. Everything below that threshold is safely downgraded to a Markdown comment for the developer to review manually. Furthermore, the local CI loop verifies that the fix didn't introduce any *new* native linting errors before pushing.

## 6. Weak LLMs Yielding Low Confidence & Poor Logic
**The Problem:** In our earliest iterations, we attempted to use smaller, open-source models (like Llama 7B) to power the PR-Agent refinement step in order to save on API costs. However, these smaller models severely lacked the reasoning capabilities required for complex codebase architectures. They consistently output low-confidence scores, missed obvious bugs, or generated hallucinated code that failed the CI loop.

**The Solution:** We abandoned the 7B models and migrated the pipeline's backbone to **Amazon Bedrock (Nova Pro)**, which provided a massive leap in reasoning, dramatically boosting the volume of high-confidence, merge-ready fixes. 

**Takeaway for Customers:** Autonomous code execution requires frontier-class reasoning. While Nova Pro is the default, the pipeline is entirely model-agnostic thanks to LiteLLM. If your codebase is exceptionally complex, we highly recommend setting your `LLM_MODEL_ID` to an Anthropic model (like `claude-3-5-sonnet-20240620`) or OpenAI's `gpt-4o` for the absolute highest tier of autonomous code generation.
