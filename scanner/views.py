import json
import base64
import re
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import BusinessCard, Company

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
                    "For the company key, extract ONLY the company name and completely ignore any job titles (like VP, CEO, etc.). "
                    "Do not use markdown backticks, explanations, or introductory text. "
                    "If a value is missing, use null."
                ),
                "stream": False,
                "images": [encoded_image]
            }
            
            response = requests.post(url, json=payload)
            result = response.json()
            ai_text = result.get('response', '').strip()
            
            json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
            else:
                clean_text = ai_text.replace('```json', '').replace('```', '').strip()
            
            try:
                parsed_data = json.loads(clean_text)
            except Exception:
                parsed_data = {"name": "Unparsed", "company": None, "email": None, "phone": None}
                
            full_name = parsed_data.get('name', '') or ''
            name_parts = full_name.split(' ', 1)
            f_name = name_parts[0] if len(name_parts) > 0 else ''
            l_name = name_parts[1] if len(name_parts) > 1 else ''
            
            email_val = parsed_data.get('email')
            phone_val = parsed_data.get('phone')
            extracted_company = parsed_data.get('company')
            
            is_dup = False
            if email_val:
                if BusinessCard.objects.filter(user=request.user, email=email_val).exists():
                    is_dup = True
            if phone_val and not is_dup:
                if BusinessCard.objects.filter(user=request.user, phone_number=phone_val).exists():
                    is_dup = True

            linked_company_obj = None
            if extracted_company:
                linked_company_obj, created = Company.objects.get_or_create(
                    user=request.user,
                    name=extracted_company
                )
            
            BusinessCard.objects.create(
                user=request.user,
                first_name=f_name,
                last_name=l_name,
                company_name=extracted_company,
                company_link=linked_company_obj,
                email=email_val,
                phone_number=phone_val,
                manual_note=user_note,
                card_image=image_file,
                is_approved=False,
                is_duplicate=is_dup
            )
            return JsonResponse(parsed_data)
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return render(request, 'scanner/index.html')

@login_required
def dashboard(request):
    approved_cards = BusinessCard.objects.filter(user=request.user, is_approved=True).order_by('-scanned_at')
    pending_cards = BusinessCard.objects.filter(user=request.user, is_approved=False).order_by('-scanned_at')
    
    total_cards = approved_cards.count()
    unique_companies = approved_cards.values('company_name').distinct().exclude(company_name__isnull=True).exclude(company_name='').count()
    
    context = {
        'approved_cards': approved_cards,
        'pending_cards': pending_cards,
        'total_cards': total_cards,
        'unique_companies': unique_companies,
    }
    return render(request, 'scanner/view.html', context)

@login_required
def approve_card(request, card_id):
    if request.method == 'POST':
        card = get_object_or_404(BusinessCard, id=card_id, user=request.user)
        card.is_approved = True
        card.is_duplicate = False
        card.save()
    return redirect('/dashboard/')

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
        user_cards = BusinessCard.objects.filter(user=request.user, is_approved=True)
        
        context_data = "Saved Contacts:\n"
        for card in user_cards:
            context_data += f"- Name: {card.first_name} {card.last_name}, Company: {card.company_name}, Email: {card.email}, Phone: {card.phone_number}, Notes: {card.manual_note}\n"
            
        prompt = (
            "You are a friendly, professional CRM assistant. Answer the user's question using ONLY the provided contact data. "
            "Write in complete, natural sentences. If asked about a person, provide a helpful summary of their company, contact info, and notes. "
            "If the information is not in the data, say you don't know.\n\n"
            f"Data:\n{context_data}\n\n"
            f"Question: {user_message}"
        )
        
        try:
            response = requests.post("http://localhost:11434/api/generate", json={"model": "llama3.2-vision", "prompt": prompt, "stream": False})
            return JsonResponse({'answer': response.json().get('response', 'Error.')})
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
        card.is_approved = False
        card.save()
    return redirect('/dashboard/')
@login_required
def company_network(request, company_id):
    # Find the specific company
    company = get_object_or_404(Company, id=company_id, user=request.user)
    
    # Grab all approved employees linked to this company
    employees = company.employees.filter(is_approved=True).order_by('-scanned_at')
    
    return render(request, 'scanner/company.html', {
        'company': company,
        'employees': employees,
        'employee_count': employees.count()
    })