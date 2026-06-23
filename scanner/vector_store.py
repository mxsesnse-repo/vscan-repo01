import logging

logger = logging.getLogger(__name__)

try:
    import chromadb
    _chroma_client = None
    _chroma_collection = None

    def _get_collection():
        global _chroma_client, _chroma_collection
        if _chroma_collection is None:
            _chroma_client = chromadb.PersistentClient(path="./chroma_db")
            _chroma_collection = _chroma_client.get_or_create_collection(
                name="business_card_crm"
            )
        return _chroma_collection

    CHROMA_AVAILABLE = True

except Exception as e:
    logger.warning(f"ChromaDB not available: {e}")
    CHROMA_AVAILABLE = False


def upsert_vector(vector_id, embedding, text, metadata):
    if not CHROMA_AVAILABLE:
        logger.warning("ChromaDB unavailable, skipping upsert")
        return
    try:
        _get_collection().upsert(
            ids=[vector_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )
    except Exception as e:
        logger.error(f"ChromaDB upsert failed: {e}")


def search_vectors(query_embedding, top_k=10, filters=None):
    if not CHROMA_AVAILABLE:
        logger.warning("ChromaDB unavailable, returning empty results")
        return {"ids": [[]], "documents": [[]], "metadatas": [[]]}
    try:
        return _get_collection().query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=filters or None,
        )
    except Exception as e:
        logger.error(f"ChromaDB search failed: {e}")
        return {"ids": [[]], "documents": [[]], "metadatas": [[]]}