import base64
import json
import re
import requests
from io import BytesIO
from PIL import Image
from celery import shared_task
from django.utils import timezone

from .models import BusinessCard, Company, KnowledgeDocument, DocumentChunk, EmbeddingIndexMap
from .rag_services import build_card_document, calculate_hash, chunk_text, embed_text
from .vector_store import upsert_vector

OLLAMA_URL = "http://localhost:11434/api/generate"
VISION_MODEL = "llama3.2-vision"

@shared_task
def process_business_card(card_id):
    try:
        card = BusinessCard.objects.get(id=card_id)

        img = Image.open(card.card_image)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((800, 800))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        encoded_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

        prompt = """Extract contact details from the business card image.
You MUST return ONLY a raw JSON object. Do not wrap it in markdown. Do not add any text before or after the JSON.
Use exactly these keys:
{
  "full_name": null,
  "designation": null,
  "company_name": null,
  "email": null,
  "phone": null,
  "website": null,
  "address": null
}"""

        payload = {
            "model": VISION_MODEL,
            "prompt": prompt,
            "images": [encoded_image],
            "stream": False,
            "format": "json"
        }

        response = requests.post(OLLAMA_URL, json=payload, timeout=180)
        response.raise_for_status()
        ai_text = response.json().get("response", "").strip()

        card.raw_ai_response = ai_text

        clean_text = ai_text
        json_match = re.search(r"\{.*\}", ai_text, re.DOTALL)
        if json_match:
            clean_text = json_match.group(0)

        try:
            parsed = json.loads(clean_text)
        except Exception:
            parsed = {"parse_error": True, "raw_text": ai_text}

        card.extracted_json = parsed

        if not parsed.get("parse_error"):
            full_name = parsed.get("full_name") or ""
            first = ""
            last = ""

            if full_name:
                parts = full_name.split(" ", 1)
                first = parts[0]
                last = parts[1] if len(parts) > 1 else ""

            if first:
                card.first_name = first
            elif card.first_name == "Processing...":
                card.first_name = "Unknown"

            if last:
                card.last_name = last

            if parsed.get("designation"):
                card.designation = parsed.get("designation")
            if parsed.get("email"):
                card.email = parsed.get("email")
            if parsed.get("phone"):
                card.phone_number = parsed.get("phone")
            if parsed.get("website"):
                card.website = parsed.get("website")
            if parsed.get("address"):
                card.address = parsed.get("address")
            if parsed.get("company_name"):
                card.company_name = parsed.get("company_name")

            extracted_company = parsed.get("company_name")
            if extracted_company:
                company_obj, _ = Company.objects.get_or_create(
                    user=card.user,
                    name=extracted_company,
                    defaults={"normalized_name": " ".join(extracted_company.lower().strip().split())},
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
    card = BusinessCard.objects.select_related("company_link", "met_at_event").prefetch_related("domains").get(id=card_id)

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