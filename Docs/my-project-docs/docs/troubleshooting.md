---
sidebar_position: 8
title: Troubleshooting
---

# Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Pipeline never triggers on new PRs | Branch policy not set to **Required**/**Automatic** | Re-check [Azure DevOps Setup → Step 3](/docs/azure-devops#3-configure-branch-policy-trigger-on-pr) |
| `401 Unauthorized` when pushing/commenting | Build service identity missing repo permissions | Re-check [Azure DevOps Setup → Step 4](/docs/azure-devops#4-grant-permission-to-push-code--comment) |
| Agent keeps re-running on its own commits | Loop-guard misidentifying author, or `fetchDepth` too shallow to see the source commit | Ensure the pipeline checkout uses `fetchDepth: 0` |
| Bedrock calls fail with access errors | Model not enabled in the target region, or IAM policy too narrow | Confirm model access is granted in the AWS Bedrock console for your region |
| Fixes committed but agent PR never opens | `aider_fix_applied` is `False` (nothing to fix) or PR creation call failed silently | Check `create_agent_pr.py` logs — errors there don't fail the pipeline, only get logged |
| Findings look inconsistent between runs | Non-zero `temperature` or model non-determinism | `temperature` is already set to `0` in `call_bedrock_review` — verify no other code path overrides it |

## Diagnostic Checklist

If the pipeline runs but produces unexpected results, work through these in order:

1. **Check the pipeline logs for `ingestion_done`** — confirms which files were actually picked up. If your file extension isn't `.py` or `.sql`, see [Customization](/docs/customization) to extend the filter.
2. **Check for `code_quality_review_error` / `security_audit_review_error` / `performance_review_error`** — these indicate the Bedrock call itself failed (usually IAM/region/model-access issues).
3. **Check `aider_llm_fix_no_high_confidence_findings`** — means no findings met the `MIN_FIX_CONFIDENCE` threshold; lower the threshold in your Variable Group if this happens too often.
4. **Check `agent_branch_checkout_failed`** — the pipeline aborted rather than risk editing the wrong branch; verify the agent branch naming doesn't collide with an existing protected branch.
5. **Check `local_ci_max_attempts_reached`** — the CI-fix loop hit its retry cap; the PR will still be raised, but flagged as CI-failing in the comment.

If none of these explain the behavior you're seeing, open an issue on [GitLab](https://gitlab.com/adityasah104/ai-review-agent-pipeline/issues) with the relevant log excerpt.