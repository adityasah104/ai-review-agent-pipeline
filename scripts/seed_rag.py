"""
Run this once before starting the agent to seed ChromaDB with guidelines.
Usage: python scripts/seed_rag.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rag.indexer import seed_guidelines
import structlog

log = structlog.get_logger()

if __name__ == "__main__":
    log.info("seeding_chromadb_guidelines")
    seed_guidelines()
    log.info("seeding_complete")
    print("✅ ChromaDB seeded successfully.")