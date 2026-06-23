import hashlib
import os
import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_EMBED_URL = f"{OLLAMA_HOST}/api/embed"
EMBED_MODEL = "nomic-embed-text"


def calculate_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_card_document(card):
    company_name = (
        card.company_link.name if card.company_link else (card.company_name or "Unknown company")
    )
    event_name = card.met_at_event.name if card.met_at_event else "No event"
    domain_names = ", ".join([d.name for d in card.domains.all()])

    text = f"""Contact: {card.full_name}
Designation: {card.designation or "Not available"}
Contact Type: {card.get_contact_type_display() if card.contact_type else "Not available"}
Company: {company_name}
Email: {card.email or "Not available"}
Phone: {card.phone_number or "Not available"}
Website: {card.website or "Not available"}
Address: {card.address or "Not available"}
Source Event: {event_name}
Domains: {domain_names or "Not tagged"}
Notes: {card.manual_note or "No notes available"}"""

    metadata = {
        "entity_type": "contact",
        "contact_id": card.id,
        "company": company_name,
        "event": event_name,
        "domains": domain_names,
        "contact_type": card.contact_type,
        "owner_id": card.user_id,
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


def embed_text(text):
    payload = {"model": EMBED_MODEL, "input": text}
    response = requests.post(OLLAMA_EMBED_URL, json=payload, timeout=120)
    response.raise_for_status()
    data = response.json()
    if "embeddings" in data and len(data["embeddings"]) > 0:
        return data["embeddings"][0]
    raise ValueError("API response did not contain expected embedding data.")