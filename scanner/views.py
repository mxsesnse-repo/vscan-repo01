import json
import base64
import urllib.request
import os
from dotenv import load_dotenv
from django.shortcuts import render
from django.http import JsonResponse
from .models import BusinessCard

load_dotenv()

def scan_card(request):
    if request.method == 'POST' and request.FILES.get('image'):
        try:
            image_file = request.FILES['image']
            user_note = request.POST.get('manual_note', '')
            
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
            mime_type = image_file.content_type
            
            api_key = os.getenv("GEMINI_API_KEY")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": "Extract contact details from this card. Return ONLY a JSON object with: name, email, phone, company. Use null if not found."},
                        {"inline_data": {"mime_type": mime_type, "data": encoded_image}}
                    ]
                }]
            }
            
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'), 
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                
            ai_text = result['candidates'][0]['content']['parts'][0]['text']
            clean_text = ai_text.replace('```json', '').replace('```', '').strip()
            parsed_data = json.loads(clean_text)
            
            full_name = parsed_data.get('name', '') or ''
            name_parts = full_name.split(' ', 1)
            f_name = name_parts[0] if len(name_parts) > 0 else ''
            l_name = name_parts[1] if len(name_parts) > 1 else ''
            
            BusinessCard.objects.create(
                first_name=f_name,
                last_name=l_name,
                company_name=parsed_data.get('company'),
                email=parsed_data.get('email'),
                phone_number=parsed_data.get('phone'),
                manual_note=user_note,
                card_image=image_file
            )
            
            return JsonResponse(parsed_data)
            
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            return JsonResponse({'error': str(e), 'google_details': error_body}, status=500)
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return render(request, 'scanner/index.html')

def dashboard(request):
    cards = BusinessCard.objects.all().order_by('-scanned_at')
    return render(request, 'scanner/view.html', {'cards': cards})