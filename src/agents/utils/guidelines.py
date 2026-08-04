import os
from pathlib import Path

def load_guidelines(category: str) -> str:
    """Reads the specific markdown file for the given category from the src/guidelines directory."""
    guidelines_dir = Path(__file__).resolve().parent.parent.parent / "guidelines"
    file_path = guidelines_dir / f"{category}.md"
    
    if file_path.exists() and file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass
            
    return "- No custom guidelines provided."
