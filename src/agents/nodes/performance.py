import json
import boto3
import structlog
from src.agents.state import PRReviewState
from src.config.settings import settings

log = structlog.get_logger()


def _call_bedrock(prompt: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=settings.AWS_REGION)
    body = {
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
    return result["output"]["message"]["content"][0]["text"]


async def run(state: PRReviewState) -> dict:
    """Reviews code for performance issues using Bedrock Nova Pro."""
    log.info("performance_review_start")

    if not state.file_contents:
        return {"findings": []}

    # Build file text with explicit line numbers
    files_text = ""
    for path, content in state.file_contents.items():
        # Add line numbers to full content
        lines = content.split('\n')
        numbered_lines = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]
        numbered_content = "\n".join(numbered_lines)
        
        diff = state.file_diffs.get(path, "No diff available.")
        
        files_text += f"\n\n### File: {path}\n"
        files_text += f"--- FULL FILE WITH LINE NUMBERS ---\n```\n{numbered_content[:8000]}\n```\n"
        files_text += f"--- CHANGED LINES (diff) ---\n```diff\n{diff[:4000]}\n```\n"

    prompt = f"""You are a ruthless performance engineering expert reviewing Python and SQL code.                                                
                                                                                                                                                 
    CRITICAL RULES (violating any of these makes your review invalid):                                                                           
    1. DO NOT invent or hallucinate issues. If the code is perfectly fine, return an empty                                                       
       array []. You are NOT required to find a problem. Zero findings is a completely                                                           
       normal, acceptable, and often correct result.                                                                                             
    2. DO NOT change or complain about business logic. If a developer explicitly selects                                                         
       specific columns (e.g., SELECT col1, col2), do not suggest changing it, renaming                                                          
       it, reordering it, or adding/removing columns from it.                                                                                    
    3. In SQL, ONLY flag SELECT * as a bad practice regarding column selection. Never                                                            
       complain about explicit column selections — an explicit column list is always                                                             
       correct, no matter how it's styled or ordered.                                                                                            
    4. If a piece of code is stylized a certain way but is functionally correct and not a                                                        
       security risk, leave it alone. Do not report subjective style preferences,                                                                
       nitpicks, or theoretical micro-optimizations.                                                                                             
                                                                                                                                                 
    Review the following code for SEVERE PERFORMANCE issues only.                                                                                
    You MUST ONLY report actionable bottlenecks that require an immediate code change.                                                           
    DO NOT report micro-optimizations, theoretical scaling concerns, or minor nitpicks.                                                          
                                                                                                                                                 
    Look for:                                                                                                                                    
    N+1 query patterns in Python (loops that execute database queries)                                                                           
    Inefficient JOINs or missing partition/cluster keys in dbt models                                                                            
    SELECT * in SQL (fetches unnecessary columns)                                                                                                
    Large result sets loaded entirely into memory in Python                                                                                      
    Inefficient list comprehensions vs generators for massive data                                                                               
    dbt models missing incremental materializations for large tables                                                                             
    Repeated expensive function calls inside loops                                                                                               
    SQL DISTINCT or ORDER BY on large unsorted datasets without purpose                                                                          
                                                                                                                                                 
    Here is the code context. You are provided with the full file (with line numbers on the left) and the git diff:                              
    {files_text}                                                                                                                                 
  
    IMPORTANT: Only report issues introduced in the changed lines (shown in the diff).
    Do NOT flag pre-existing issues in unchanged context lines.
    If an issue does not absolutely require a code change, IGNORE IT.
    Before returning a finding, double-check it does not violate any of the CRITICAL RULES above.
    NEVER emit generic, unactionable advice like "Ensure the function is correctly defined and used". If a bug isn't explicitly identifiable, SKIP IT.
    It is far better to return [] than to report a false or unnecessary finding.
  
    Return your findings as a JSON array. Each finding must have:
    file_path: string
    line_number: integer — the exact line number from the FULL FILE WITH LINE NUMBERS block (left side of the |). This field MUST be called      
  line_number, NOT file_number. Example: if the code shows 42 | def foo():, then line_number is 42.
    severity: "critical" or "major" (DO NOT return "minor")
    category: "performance"
    description: string (clear explanation of the severe bottleneck)
    suggestion: string
    confidence: float (0.0 to 1.0)
  
    Return ONLY the JSON array, no other text. If no issues found, return [].
    """

    try:
        response_text = _call_bedrock(prompt)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        findings = json.loads(cleaned)
        if not isinstance(findings, list):
            findings = []

        log.info("performance_review_done", findings_count=len(findings))
        return {"findings": findings}

    except Exception as e:
        log.error("performance_review_error", error=str(e))
        return {"findings": []}