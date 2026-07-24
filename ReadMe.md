# AI PR Review Agent — Project Documentation

> **Platform:** Azure DevOps · Amazon Bedrock · LangGraph  
> **Model:** Amazon Nova Pro (via AWS Bedrock)  
> **Engine:** Aider (v0.86.2+) + PR-Agent  
> **Linters:** Ruff (Python), SQLFluff (SQL/dbt)  

---

## 1. Project Overview: What Are We Trying to Achieve?

The goal of this project is to build a **fully autonomous, end-to-end Pull Request Review & Auto-Fix Pipeline**. 

Unlike traditional static analysis tools or basic AI bots that simply leave annoying comments on a PR for a developer to fix manually, this agent acts as a true Senior Software Engineer. When a PR is opened, the agent:
1. Audits the code for critical security vulnerabilities, logic bugs, and code quality issues.
2. Checks out the code locally.
3. Automatically writes and applies the fixes for the developer.
4. Runs native formatting tools to clean up the code.
5. Runs a strict CI linting loop to guarantee it didn't break the build.
6. Pushes a perfectly green, ready-to-merge branch back to the repository.

---

## 2. Current State: What Is It Solving Right Now?

The pipeline is currently highly robust and capable of surviving "worst-case scenario" codebases. In our latest stress tests, it successfully handled:

* **Critical Security Fixes:** Autonomously identified and patched SQL injections (converting `f-strings` to parameterized queries), removed hardcoded AWS Secrets, and replaced insecure `eval()` deserialization with safe `json.loads()`.
* **Hybrid Formatting Pipeline:** Implemented a highly efficient two-step formatting process. First, it runs native tools (`ruff check --fix` and `ruff format`) to deterministically solve 90% of formatting issues in milliseconds.
* **Intelligent CI Fallback Loop:** If the native linters fail (e.g., a bare `except:` block, or an `E402` import ordering rule), the pipeline captures the exact CLI error output and feeds it back to the AI. The AI is strictly instructed to fix the build without touching business logic.
* **Edge-Case Handling:** We upgraded the AI to use an aggressive `--edit-format whole` strategy, allowing it to easily parse and rewrite completely unformatted, messy files that would normally break standard AI diff-checkers. It also knows how to safely suppress unfixable linter rules (e.g., appending `# noqa: E402`) to prevent infinite loops.

---

## 3. Current Limitations & Risks

While the pipeline is highly capable, it currently faces a few technical hurdles dictated by the underlying LLM:

1. **The Truncation Risk (Token Limits):** Because the pipeline currently relies on the `--edit-format whole` strategy to avoid diff-formatting failures, the AI must re-type every file from top to bottom. For massive files, the model (`amazon.nova-pro`) can hit its maximum output token limit or get "lazy," resulting in silent deletion of code at the bottom of the file (e.g., dropping `if __name__ == "__main__":` blocks). 
2. **Missing Minor Bugs:** The agent prioritizes critical security issues. If a file contains a severe vulnerability alongside a minor code smell (like a mutable default argument), the LLM occasionally fixes the critical bug and forgets to apply the minor fix in the same pass.
3. **Diff-Fenced Formatting Struggles:** The `amazon.nova-pro` model struggles to consistently output perfect unified diffs (search/replace blocks). This is why we were forced to switch to rewriting the whole file, which directly causes limitation #1.

---

## 4. Future Improvement Roadmap

To make this pipeline 100% bulletproof for enterprise production, the following upgrades are recommended:

1. **Model Upgrade (The Silver Bullet):** Switch the backend model from Amazon Nova Pro to **Claude 3.5 Sonnet**. Claude is the industry gold-standard for generating surgical, flawless diff blocks. Upgrading the model would allow us to revert back to `--edit-format diff-fenced`, completely eliminating the truncation risk while maintaining a 100% bug-fix rate.
2. **Unit Test Integration in the CI Loop:** Currently, the CI loop only validates that the Python syntax is correct and lint-free. In the future, the pipeline should run `pytest` in the loop so the AI can verify it didn't accidentally break business logic.
3. **Stricter Pre-Commit Hooks:** Integrating tools like `isort` natively into the pipeline before the AI runs will drastically reduce the number of import-related edge cases (`E402`) the AI has to waste tokens trying to solve.

---

## 5. Comparison: Existing PR Review Tools

There are several commercial tools on the market that attempt to solve this problem, including **CodeRabbit**, **SonarQube**, **GitHub Copilot PR Review**, and **Codium PR-Agent** (which we use under the hood). 

### How This Project is Better
Most existing tools fall into the "Glorified Chatbot" category. They scan the code and post markdown comments on the PR (e.g., *"You have a SQL injection here, click this button to accept my suggestion"*). 
* **The Problem with Competitors:** The developer still has to manually review the suggestions, accept them, pull the code, run their local linters, realize the AI's suggestion broke the formatting, fix the formatting manually, and push again.
* **Our Advantage:** This project is a **True Autonomous Agent**. It actually checks out the workspace, applies the fixes, runs the local linters (`ruff`), and uses a self-healing CI loop to guarantee the code works *before* human eyes ever see it.

### Where This Project Lags
* **UI and Dashboards:** Tools like CodeRabbit and SonarQube have massive enterprise web dashboards for tracking metrics, vulnerabilities, and team performance over time. This project is a headless backend pipeline.
* **Context Window Awareness:** Commercial tools like Sweep.dev use highly advanced RAG (Retrieval-Augmented Generation) to map the entire repository's architecture before fixing a bug. Our agent currently relies heavily on Aider's local file mapping, which is excellent but can sometimes miss deep architectural context in massive monorepos. 

---
*Maintained by the AI Review Agent Team*
