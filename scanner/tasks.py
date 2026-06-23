import base64
import json
import re
import os
import requests
from io import BytesIO
from PIL import Image
from celery import shared_task
from django.utils import timezone
import psutil

from .models import (
    SystemTelemetry,
    BusinessCard,
    Company,
    KnowledgeDocument,
    DocumentChunk,
    EmbeddingIndexMap,
)
from .rag_services import build_card_document, calculate_hash, chunk_text, embed_text
from .vector_store import upsert_vector

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_URL = f"{OLLAMA_HOST}/api/generate"
VISION_MODEL = "llava-phi3"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_RE = re.compile(r'(\+?\d{1,4}[\s.\-]?)?\(?\d{2,5}\)?[\s.\-]?\d{3,5}[\s.\-]?\d{3,5}')
URL_RE   = re.compile(r'(https?://)?(www\.)?[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+(/\S*)?')

# ---------------------------------------------------------------------------
# Blocklists
# ---------------------------------------------------------------------------

# Values that are definitely NOT a real person name
_NAME_BLOCKLIST = {
    # Template placeholders
    "name here", "full name", "n/a", "null", "none", "unknown",
    # Office/department labels
    "corporate office", "head office", "registered office", "branch office",
    "regional office", "zonal office", "area office",
    "customer care", "service helpline", "contact", "info",
    # Job titles (model sometimes puts these in full_name when there's no person)
    "managing director", "director", "manager", "executive",
    "general manager", "chairman", "president",
    "ceo", "cto", "cfo", "coo", "vp", "svp", "evp",
    "co-founder", "founder", "partner", "associate",
    "consultant", "advisor", "analyst",
}

# City/location names commonly appended to titles ("Managing Director, New Delhi")
_CITY_WORDS = {
    "new delhi", "delhi", "mumbai", "bangalore", "bengaluru", "chennai",
    "hyderabad", "kolkata", "pune", "ahmedabad", "jaipur", "surat",
    "singapore", "london", "new york", "dubai", "hong kong",
}

# Job-title words used in comma-split checks
_TITLE_WORDS = {
    "director", "manager", "managing director", "ceo", "cfo", "cto", "coo",
    "president", "chairman", "executive", "officer", "head", "co-founder",
    "founder", "partner", "vp", "svp", "evp", "consultant", "advisor",
}

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _clean_field(value) -> str:
    """Normalise a raw parsed value to a clean string, or '' if empty/null."""
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in ("null", "none", "n/a", "not found", "not available", ""):
        return ""
    return s


def _is_placeholder(value: str) -> bool:
    """Return True if the value looks like an unfilled template placeholder or known bad value."""
    if not value:
        return True
    lower = value.lower().strip()
    if lower in _NAME_BLOCKLIST:
        return True
    if lower.endswith(" here"):          # "Name Here", "Company Here", "Website Here"
        return True
    if lower == "email@example.com":
        return True
    if lower in ("null", "none", "n/a", "", "not found", "not available"):
        return True
    return False


def _looks_like_address(value: str) -> bool:
    """
    Heuristic: does this string look more like a street address than a person name?
    Triggered when 2+ signals match.
    """
    address_signals = [
        r'\d{2,}',                        # multi-digit number (street no / pincode)
        r'\b(street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|crescent|'
        r'nagar|plot|block|floor|flat|#|sector|phase|industrial)\b',
        r'\b(singapore|delhi|mumbai|chennai|bangalore|hyderabad|kolkata|pune)\b',
        r',\s*\d{5,}',                    # ", 139951" style postcode
        r'\b(near|opposite|opp\.?|behind|next to|above)\b',
    ]
    lower = value.lower()
    return sum(bool(re.search(p, lower)) for p in address_signals) >= 2


def _looks_like_title_city_combo(value: str) -> bool:
    """
    Catch patterns like "Managing Director, New Delhi" or "CEO, Mumbai"
    being mistakenly placed in full_name.
    """
    if "," not in value:
        return False
    parts = [p.strip().lower() for p in value.split(",")]
    return any(p in _TITLE_WORDS or p in _CITY_WORDS for p in parts)


def _name_is_valid(value: str) -> bool:
    """Return True only if value looks like a genuine human name."""
    if not value:
        return False
    if _is_placeholder(value):
        return False
    if _looks_like_address(value):
        return False
    if _looks_like_title_city_combo(value):
        return False
    # Must contain at least one alphabetic character
    if not re.search(r'[A-Za-z]', value):
        return False
    # Reject if it's suspiciously long (addresses / multi-line OCR)
    if len(value) > 60:
        return False
    return True

# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Best-effort JSON extraction from a model response that may have markdown fences."""
    clean = text.strip()
    clean = re.sub(r'^```json\s*', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^```\s*', '', clean)
    clean = re.sub(r'\s*```$', '', clean)
    clean = clean.strip()

    match = re.search(r'\{[\s\S]*\}', clean)
    if match:
        clean = match.group(0)

    try:
        parsed = json.loads(clean)
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else {}
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}

# ---------------------------------------------------------------------------
# Regex fallback for missing fields
# ---------------------------------------------------------------------------

def _regex_fallback(ai_text: str, parsed: dict) -> dict:
    """
    Fill missing/placeholder fields using regex against the raw OCR text.
    Mutates `parsed` in place and returns it.
    """
    email_val = _clean_field(parsed.get("email"))
    if _is_placeholder(email_val) or "@" not in email_val:
        m = EMAIL_RE.search(ai_text)
        if m:
            parsed["email"] = m.group(0)

    if _is_placeholder(_clean_field(parsed.get("phone"))):
        m = PHONE_RE.search(ai_text)
        if m:
            parsed["phone"] = m.group(0)

    if _is_placeholder(_clean_field(parsed.get("website"))):
        for m in URL_RE.finditer(ai_text):
            candidate = m.group(0)
            if "@" not in candidate:
                parsed["website"] = candidate
                break

    return parsed

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """You are a business card OCR and data extraction engine.
Extract information from the business card image and return ONLY a valid JSON object — no explanation, no markdown, no extra text.

Rules:
- "full_name" must be a real human personal name (first + last name of an individual person).
  Do NOT use: address text, company names, job titles, department names (e.g. "Corporate Office"), city names, or placeholder words.
  Some cards belong to a company and have NO individual's name on them — in that case, full_name MUST be null.
  If you are not certain a value is a real person's name, use null.
- "designation" is the job title or role (e.g. "Managing Director", "CEO"). If absent, use null.
- "company_name" is the organisation or brand name printed on the card. If absent, use null.
- "email" must contain "@". If absent, use null.
- "phone" is a numeric phone/mobile number. If absent, use null.
- "website" must look like a URL (e.g. www.example.com). Do NOT put an email address here. If absent, use null.
- "address" is the physical/mailing address. If absent, use null.
- NEVER copy example placeholder values like "Name Here", "email@example.com", or "Website Here". Use null instead.

Return exactly this JSON structure and nothing else:
{
  "full_name": <string or null>,
  "designation": <string or null>,
  "company_name": <string or null>,
  "email": <string or null>,
  "phone": <string or null>,
  "website": <string or null>,
  "address": <string or null>
}"""

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@shared_task
def process_business_card(card_id):
    try:
        card = BusinessCard.objects.get(id=card_id)

        # --- Image prep ---
        img = Image.open(card.card_image)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((800, 800))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        encoded_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # --- Model call ---
        payload = {
            "model": VISION_MODEL,
            "prompt": EXTRACTION_PROMPT,
            "images": [encoded_image],
            "stream": False,
        }
        response = requests.post(OLLAMA_URL, json=payload, timeout=600)
        response.raise_for_status()
        ai_text = response.json().get("response", "").strip()
        card.raw_ai_response = ai_text

        # --- Parse ---
        parsed = _extract_json(ai_text)
        parsed = _regex_fallback(ai_text, parsed)
        card.extracted_json = parsed

        # --- Name ---
        full_name = _clean_field(parsed.get("full_name"))

        if _name_is_valid(full_name):
            parts = full_name.split(" ", 1)
            card.first_name = parts[0]
            card.last_name  = parts[1] if len(parts) > 1 else ""
        else:
            # Don't overwrite a previously good name
            if card.first_name in ("Pending", "Processing...", "Unknown", ""):
                card.first_name = "Unknown"
            if card.last_name in ("Extraction...", "Processing..."):
                card.last_name = ""

        # --- Helper to apply a scalar field safely ---
        def _apply(card_attr, parsed_key):
            val = _clean_field(parsed.get(parsed_key))
            if val and not _is_placeholder(val):
                setattr(card, card_attr, val)

        _apply("designation",  "designation")
        _apply("email",        "email")
        _apply("phone_number", "phone")
        _apply("website",      "website")
        _apply("address",      "address")

        # --- Company ---
        extracted_company = _clean_field(parsed.get("company_name"))
        if extracted_company and not _is_placeholder(extracted_company):
            card.company_name = extracted_company
            company_obj, _ = Company.objects.get_or_create(
                user=card.user,
                name=extracted_company,
                defaults={
                    "normalized_name": " ".join(extracted_company.lower().strip().split())
                },
            )
            card.company_link = company_obj

        card.error_message = None
        card.save()
        return f"Successfully processed card {card_id}"

    except requests.exceptions.Timeout:
        msg = f"Ollama timed out for card {card_id}"
        BusinessCard.objects.filter(id=card_id).update(error_message=msg)
        return f"Error: {msg}"
    except Exception as exc:
        msg = str(exc)
        BusinessCard.objects.filter(id=card_id).update(error_message=msg)
        return f"Error processing card {card_id}: {msg}"


@shared_task
def index_contact_for_rag(card_id):
    card = (
        BusinessCard.objects.select_related("company_link", "met_at_event")
        .prefetch_related("domains")
        .get(id=card_id)
    )

    text, metadata = build_card_document(card)
    source_hash = calculate_hash(text)

    doc, created = KnowledgeDocument.objects.get_or_create(
        entity_type="contact",
        entity_id=card.id,
        defaults={
            "text_content": text,
            "metadata": metadata,
            "source_hash": source_hash,
            "index_status": "pending",
        },
    )

    if not created and doc.source_hash == source_hash and doc.index_status == "indexed":
        return f"Skipped card {card.id} — no changes detected."

    doc.text_content = text
    doc.metadata = metadata
    doc.source_hash = source_hash
    doc.index_status = "pending"
    doc.save()

    doc.chunks.all().delete()
    chunks = chunk_text(text)

    for order, chunk_str in enumerate(chunks):
        chunk_obj = DocumentChunk.objects.create(
            document=doc, chunk_text=chunk_str, chunk_order=order, metadata=metadata
        )
        embedding = embed_text(chunk_str)
        vector_id = f"contact-{card.id}-chunk-{chunk_obj.id}"
        upsert_vector(
            vector_id=vector_id,
            embedding=embedding,
            text=chunk_str,
            metadata={**metadata, "document_id": doc.id, "chunk_id": chunk_obj.id},
        )
        EmbeddingIndexMap.objects.create(
            chunk=chunk_obj,
            vector_id=vector_id,
            embedding_model="nomic-embed-text",
            index_backend="chroma",
        )

    doc.index_status = "indexed"
    doc.last_indexed_at = timezone.now()
    doc.save(update_fields=["index_status", "last_indexed_at"])

    return f"Successfully embedded and indexed card {card.id}"