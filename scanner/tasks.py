import base64
import json
import re
import requests
from io import BytesIO
from PIL import Image
from celery import shared_task
from .models import BusinessCard, Company
from django.utils import timezone
from .models import KnowledgeDocument, DocumentChunk, EmbeddingIndexMap
from .rag_services import build_card_document, calculate_hash, chunk_text, embed_text
from .vector_store import upsert_vector

@shared_task
def process_business_card(card_id):
    try:
        card = BusinessCard.objects.get(id=card_id)
        
        img = Image.open(card.card_image)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        img.thumbnail((800, 800))
        
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        encoded_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": "llama3.2-vision",
            "prompt": (
                "Extract contact details from this business card. "
                "Output ONLY a valid JSON object. "
                "Use exactly this format: {\"name\": \"\", \"email\": \"\", \"phone\": \"\", \"company\": \"\"}"
            ),
            "format": "json",
            "stream": False,
            "images": [encoded_image]
        }
        
        response = requests.post(url, json=payload, timeout=600)
        response.raise_for_status()
        result = response.json()
        
        ai_text = result.get('response', '').strip()
        
        print(f"\n--- RAW AI OUTPUT START ---\n{ai_text}\n--- RAW AI OUTPUT END ---\n")
        
        json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        clean_text = json_match.group(0) if json_match else ai_text.replace('```json', '').replace('```', '').strip()
        
        try:
            parsed_data = json.loads(clean_text)
        except Exception:
            parsed_data = {
                "name": re.search(r'(?i)name:\s*(.+)', clean_text).group(1).strip() if re.search(r'(?i)name:\s*(.+)', clean_text) else "Unparsed",
                "email": re.search(r'(?i)email:\s*(.+)', clean_text).group(1).strip() if re.search(r'(?i)email:\s*(.+)', clean_text) else None,
                "phone": re.search(r'(?i)phone:\s*(.+)', clean_text).group(1).strip() if re.search(r'(?i)phone:\s*(.+)', clean_text) else None,
                "company": re.search(r'(?i)company:\s*(.+)', clean_text).group(1).strip() if re.search(r'(?i)company:\s*(.+)', clean_text) else None
            }
            
        full_name = parsed_data.get('name', '') or ''
        name_parts = full_name.split(' ', 1)
        f_name = name_parts[0] if len(name_parts) > 0 else ''
        l_name = name_parts[1] if len(name_parts) > 1 else ''
        
        extracted_company = parsed_data.get('company')
        
        card.first_name = f_name
        card.last_name = l_name
        card.email = parsed_data.get('email')
        card.phone_number = parsed_data.get('phone')
        card.company_name = extracted_company
        
        if extracted_company:
            linked_company_obj, _ = Company.objects.get_or_create(
                user=card.user,
                name=extracted_company
            )
            card.company_link = linked_company_obj
            
        card.save()
        return f"Successfully processed card {card_id}"
        
    except requests.exceptions.Timeout:
        return f"Error: Ollama timed out after 10 minutes for card {card_id}"
    except Exception as e:
        return f"Error processing card {card_id}: {str(e)}"

@shared_task
def index_contact_for_rag(card_id):
    card = BusinessCard.objects.get(id=card_id)
    
    text, metadata = build_card_document(card)
    source_hash = calculate_hash(text)
    
    doc, created = KnowledgeDocument.objects.get_or_create(
        entity_type="contact",
        entity_id=card.id,
        defaults={
            "text_content": text,
            "metadata": metadata,
            "source_hash": source_hash,
            "index_status": "pending"
        }
    )
    
    if not created and doc.source_hash == source_hash and doc.index_status == "indexed":
        return f"Skipped card {card.id} - no changes detected."
        
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
            metadata={**metadata, "document_id": doc.id, "chunk_id": chunk_obj.id}
        )
        
        EmbeddingIndexMap.objects.create(
            chunk=chunk_obj, vector_id=vector_id, embedding_model="nomic-embed-text", index_backend="chroma"
        )
        
    doc.index_status = "indexed"
    doc.last_indexed_at = timezone.now()
    doc.save(update_fields=["index_status", "last_indexed_at"])
    
    return f"Successfully embedded and indexed card {card.id}"