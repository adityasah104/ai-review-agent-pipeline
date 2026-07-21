import json
import boto3
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings

log = structlog.get_logger()


def build_file_context(state: PRReviewState) -> str:
    """Builds the file context string (diffs or full files) for review prompts."""
    files_text = ""
    for path, content in state.file_contents.items():
        diff = state.file_diffs.get(path, "No diff available.")
        
        files_text += f"\n\n### File: {path}\n"
        if diff != "No diff available.":
            files_text += f"--- CHANGED LINES (diff) ---\n```diff\n{diff[:4000]}"
            if len(diff) > 4000:
                files_text += "\n[TRUNCATED — diff continues beyond this point]"
            files_text += "\n```\n"
        else:
            lines = content.split('\n')
            numbered_lines = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]
            numbered_content = "\n".join(numbered_lines)
            files_text += f"--- FULL FILE WITH LINE NUMBERS ---\n```\n{numbered_content[:8000]}"
            if len(numbered_content) > 8000:
                files_text += "\n[TRUNCATED — file continues beyond this point]"
            files_text += "\n```\n"
            
    return files_text


def call_bedrock_review(prompt: str) -> list[dict]:
    """
    Calls Amazon Bedrock Nova Pro with the given review prompt,
    cleans the response, and parses it into a list of findings (JSON).
    """
    client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
    body = {
        "system": [{"text": "You are a strict code review assistant. You ONLY report issues that exactly match the explicit checklist given to you. You do NOT use general knowledge, common sense, or best-practice opinions outside of what is explicitly listed. If a pattern is not in the checklist, you MUST ignore it entirely."}],
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        "inferenceConfig": {
            "maxTokens": 5120,
            "temperature": 0,
        },
    }
    response = client.invoke_model(
        modelId=settings.BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )

    result = json.loads(response["body"].read())
    response_text = result["output"]["message"]["content"][0]["text"]
    
    # Strip markdown code fences if present
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    findings = json.loads(cleaned)
    if not isinstance(findings, list):
        findings = []
        
    return findings
