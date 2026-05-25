import hashlib
import requests

def calculate_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def build_card_document(card):
    company_name = card.company_name or "Independent"
    event_name = card.met_at_event.name if card.met_at_event else "No Event"
    
    text = f"""
    Contact: {card.first_name} {card.last_name}
    Company: {company_name}
    Email: {card.email or "Not available"}
    Phone: {card.phone_number or "Not available"}
    Source Event: {event_name}
    Notes: {card.manual_note or "No notes available"}
    """
    
    metadata = {
        "entity_type": "contact",
        "contact_id": card.id,
        "company": company_name,
        "event": event_name,
    }
    return text.strip(), metadata

def chunk_text(text, max_chars=800):
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) <= max_chars:
            current += "\n" + paragraph
        else:
            if current:
                chunks.append(current.strip())
            current = paragraph
    if current:
        chunks.append(current.strip())
    return chunks

OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

def embed_text(text):
    payload = {"model": EMBED_MODEL, "prompt": text}
    response = requests.post(OLLAMA_EMBED_URL, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["embedding"]