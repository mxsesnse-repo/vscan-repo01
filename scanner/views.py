import json
import base64
import re
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import BusinessCard

def scan_card(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required. Please refresh and log in.'}, status=401)

    if request.method == 'POST' and request.FILES.get('image'):
        try:
            image_file = request.FILES['image']
            user_note = request.POST.get('manual_note', '')
            
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            url = "http://localhost:11434/api/generate"
            
            payload = {
                "model": "llama3.2-vision",
                "prompt": (
                    "Analyze this business card image. Extract contact details. "
                    "Return ONLY a raw JSON object with keys: 'name', 'email', 'phone', 'company'. "
                    "Do not use markdown backticks, explanations, or introductory text. "
                    "If a value is missing, use null."
                ),
                "stream": False,
                "images": [encoded_image]
            }
            
            response = requests.post(url, json=payload)
            result = response.json()
            ai_text = result.get('response', '').strip()
            
            print("--- RAW OLLAMA RESPONSE ---")
            print(ai_text)
            print("---------------------------")
            
            json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
            else:
                clean_text = ai_text.replace('```json', '').replace('```', '').strip()
            
            try:
                parsed_data = json.loads(clean_text)
            except Exception as json_err:
                print(f"JSON Parsing failed: {json_err}")
                parsed_data = {
                    "name": "Unparsed Local Extraction",
                    "company": "Check Terminal Log",
                    "email": None,
                    "phone": None
                }
                
            full_name = parsed_data.get('name', '') or ''
            name_parts = full_name.split(' ', 1)
            f_name = name_parts[0] if len(name_parts) > 0 else ''
            l_name = name_parts[1] if len(name_parts) > 1 else ''
            
            BusinessCard.objects.create(
                user=request.user,
                first_name=f_name,
                last_name=l_name,
                company_name=parsed_data.get('company'),
                email=parsed_data.get('email'),
                phone_number=parsed_data.get('phone'),
                manual_note=user_note,
                card_image=image_file
            )
            
            return JsonResponse(parsed_data)
            
        except Exception as e:
            print(f"General Scanner Exception: {e}")
            return JsonResponse({'error': str(e)}, status=500)
            
    return render(request, 'scanner/index.html')

@login_required
def dashboard(request):
    user_cards = BusinessCard.objects.filter(user=request.user).order_by('-scanned_at')
    
    total_cards = user_cards.count()
    unique_companies = user_cards.values('company_name').distinct().exclude(company_name__isnull=True).exclude(company_name='').count()
    recent_activity = user_cards[:5]
    
    context = {
        'cards': user_cards,
        'total_cards': total_cards,
        'unique_companies': unique_companies,
        'recent_activity': recent_activity
    }
    return render(request, 'scanner/view.html', context)

@login_required
def edit_card(request, card_id):
    card = get_object_or_404(BusinessCard, id=card_id, user=request.user)
    
    if request.method == 'POST':
        card.first_name = request.POST.get('first_name', '')
        card.last_name = request.POST.get('last_name', '')
        card.company_name = request.POST.get('company_name', '')
        card.email = request.POST.get('email', '')
        card.phone_number = request.POST.get('phone_number', '')
        card.manual_note = request.POST.get('manual_note', '')
        card.save()
        return redirect('/dashboard/')
        
    return render(request, 'scanner/edit.html', {'card': card})

@login_required
def chat_view(request):
    if request.method == 'POST':
        user_message = request.POST.get('message', '')
        
        user_cards = BusinessCard.objects.filter(user=request.user)
        
        context_data = "Here is the data from my saved business contacts:\n"
        for card in user_cards:
            context_data += f"- Name: {card.first_name} {card.last_name}, Company: {card.company_name}, Role/Notes: {card.manual_note}\n"
            
        prompt = (
            "You are a helpful business assistant. Use ONLY the following contact data to answer the user's question. "
            "If the answer is not in the data, say you don't know.\n\n"
            f"{context_data}\n\n"
            f"User Question: {user_message}"
        )
        
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": "llama3.2-vision", 
            "prompt": prompt,
            "stream": False
        }
        
        try:
            response = requests.post(url, json=payload)
            ai_answer = response.json().get('response', 'Sorry, I encountered an error.')
            return JsonResponse({'answer': ai_answer})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return render(request, 'scanner/chat.html')

@login_required
def delete_card(request, card_id):
    if request.method == 'POST':
        card = get_object_or_404(BusinessCard, id=card_id, user=request.user)
        card.delete()
    return redirect('/dashboard/')

@login_required
def copy_card(request, card_id):
    if request.method == 'POST':
        card = get_object_or_404(BusinessCard, id=card_id, user=request.user)
        card.pk = None 
        card.manual_note = f"[COPIED] {card.manual_note}" if card.manual_note else "[COPIED RECORD]"
        card.save()
    return redirect('/dashboard/')