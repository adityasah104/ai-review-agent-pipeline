from typing import List
from src.rag.indexer import get_collection


def retrieve_guidelines(query: str, n_results: int = 3) -> List[str]:
    """
    Queries ChromaDB for the most relevant guideline chunks.
    Returns a list of text strings.
    """
    collection = get_collection()
    count = collection.count()
    if count == 0:
        return []
        
    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, count),
    )
    documents = results.get("documents", [[]])[0]
    return documents
