import os
import chromadb
from chromadb.utils import embedding_functions
import structlog
from src.config.settings import settings

log = structlog.get_logger()

COLLECTION_NAME = "coding_guidelines"


def get_chroma_client():
    return chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)


def get_collection(client=None):
    if client is None:
        client = get_chroma_client()
    # Use the default sentence-transformers embedding function (runs locally, no API key needed)
    ef = embedding_functions.DefaultEmbeddingFunction()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
    )


def seed_guidelines():
    """
    Reads the markdown guideline files and indexes them into ChromaDB.
    Splits each file into chunks by section (## heading).
    Run this once with: python scripts/seed_rag.py
    """
    guidelines_dir = os.path.join(os.path.dirname(__file__), "..", "guidelines")
    files = {
        "python_guidelines": os.path.join(guidelines_dir, "python_guidelines.md"),
        "dbt_guidelines": os.path.join(guidelines_dir, "dbt_guidelines.md"),
    }

    client = get_chroma_client()
    collection = get_collection(client)

    # Clear existing documents before re-seeding
    existing = collection.count()
    if existing > 0:
        log.info("clearing_existing_guidelines", count=existing)
        collection.delete(where={"source": {"$in": list(files.keys())}})

    all_docs = []
    all_ids = []
    all_metadatas = []

    for source_name, file_path in files.items():
        if not os.path.exists(file_path):
            log.warning("guideline_file_not_found", path=file_path)
            continue

        with open(file_path, "r") as f:
            content = f.read()

        # Split by ## headings into chunks
        sections = content.split("\n## ")
        for i, section in enumerate(sections):
            if not section.strip():
                continue
            # Add back the ## for all but the first section
            text = section if i == 0 else f"## {section}"
            doc_id = f"{source_name}_section_{i}"
            all_docs.append(text.strip())
            all_ids.append(doc_id)
            all_metadatas.append({"source": source_name, "section": i})

    if all_docs:
        collection.add(documents=all_docs, ids=all_ids, metadatas=all_metadatas)
        log.info("guidelines_seeded", count=len(all_docs))
    else:
        log.warning("no_guidelines_seeded")