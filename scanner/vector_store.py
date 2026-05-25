import chromadb

# This will automatically create a folder called 'chroma_db' in your project root
client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection(name="business_card_crm")

def upsert_vector(vector_id, embedding, text, metadata):
    collection.upsert(
        ids=[vector_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[metadata],
    )

def search_vectors(query_embedding, top_k=10, filters=None):
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=filters or None,
    )