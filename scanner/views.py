import json
import base64
import requests
import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login, logout
from .models import BusinessCard, Company, Event, Task, Domain, Opportunity
from .graph_services import sync_card_to_graph, get_contacts_at_company_via_graph, get_contacts_by_domain_via_graph
from .tasks import process_business_card, index_contact_for_rag

def scan_card(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required. Please refresh and log in.'}, status=401)

    if request.method == 'POST' and request.FILES.get('image'):
        try:
            image_file = request.FILES['image']
            user_note = request.POST.get('manual_note', '')
            
            new_card = BusinessCard.objects.create(
                user=request.user,
                first_name="Processing...",
                last_name="AI is scanning",
                manual_note=user_note,
                card_image=image_file,
                is_approved=False
            )
            
            process_business_card.delay(new_card.id)
            return JsonResponse({'message': 'Card uploaded successfully! AI is processing in the background.'})
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return render(request, 'scanner/index.html')

@login_required
def dashboard(request):
    cards = BusinessCard.objects.filter(user=request.user, is_approved=True).order_by('-scanned_at')
    pending_cards = BusinessCard.objects.filter(user=request.user, is_approved=False)
    companies = Company.objects.filter(user=request.user).order_by('name')
    tasks = Task.objects.filter(user=request.user).order_by('due_date')
    domains = Domain.objects.filter(user=request.user).order_by('name')
    opportunities = Opportunity.objects.filter(user=request.user).select_related('contact')

    total_contacts = cards.count()
    total_companies = companies.count()
    pending_tasks = tasks.filter(is_completed=False).count()

    context = {
        'cards': cards,
        'companies': companies,
        'tasks': tasks,
        'pending_cards': pending_cards,
        'total_contacts': total_contacts,
        'total_companies': total_companies,
        'pending_tasks': pending_tasks,
        'domains': domains,
        'opportunities': opportunities
    }
    return render(request, 'scanner/view.html', context)

@login_required
def approve_card(request, card_id):
    if request.method == 'POST':
        card = get_object_or_404(BusinessCard, id=card_id, user=request.user)
        card.is_approved = True
        card.is_duplicate = False
        card.save()
        
        sync_card_to_graph(card)
        index_contact_for_rag.delay(card.id)
        
    return redirect('/dashboard/')

@login_required
def edit_card(request, card_id):
    card = get_object_or_404(BusinessCard, id=card_id, user=request.user)
    domains = Domain.objects.filter(user=request.user)
    opportunity = Opportunity.objects.filter(contact=card).first()
    
    if request.method == 'POST':
        card.first_name = request.POST.get('first_name', '')
        card.last_name = request.POST.get('last_name', '')
        card.company_name = request.POST.get('company_name', '')
        card.email = request.POST.get('email', '')
        card.phone_number = request.POST.get('phone_number', '')
        card.manual_note = request.POST.get('manual_note', '')
        card.save()
        
        selected_domain_ids = request.POST.getlist('domains')
        card.domains.set(selected_domain_ids)
        
        opp_title = request.POST.get('opp_title')
        opp_stage = request.POST.get('opp_stage', 'lead')
        opp_value = request.POST.get('opp_value')

        if opp_title: 
            if opportunity:
                opportunity.title = opp_title
                opportunity.stage = opp_stage
                opportunity.value = opp_value if opp_value else None
                opportunity.save()
            else:
                Opportunity.objects.create(
                    user=request.user,
                    contact=card,
                    title=opp_title,
                    stage=opp_stage,
                    value=opp_value if opp_value else None
                )
        
        sync_card_to_graph(card)
        return redirect('/dashboard/')
        
    return render(request, 'scanner/edit.html', {
        'card': card, 
        'domains': domains,
        'opportunity': opportunity
    })

@login_required
def chat_view(request):
    if request.method == 'POST':
        user_message = request.POST.get('message', '')
        user_cards = BusinessCard.objects.filter(user=request.user, is_approved=True).prefetch_related('opportunities')
        
        context_data = "Saved Contacts & Deals:\n"
        for card in user_cards:
            context_data += f"- Name: {card.first_name} {card.last_name}, Company: {card.company_name}\n"
            # Add opportunity/deal info to the prompt context
            for opp in card.opportunities.all():
                context_data += f"  * Deal: {opp.title}, Stage: {opp.get_stage_display()}, Value: {opp.value}\n"
            context_data += f"  * Contact Info: Email: {card.email}, Phone: {card.phone_number}, Notes: {card.manual_note}\n"
            
        prompt = (
            "You are a professional CRM assistant. Use ONLY the provided contact and deal data to answer the user. "
            "If the user asks about a deal or contact, summarize their company, deal stage, and value.\n\n"
            f"Data:\n{context_data}\n\n"
            f"Question: {user_message}"
        )
        
        try:
            response = requests.post(
                "http://localhost:11434/api/generate", 
                json={"model": "llama3.2", "prompt": prompt, "stream": False},
                timeout=60
            )
            return JsonResponse({'answer': response.json().get('response', 'Error.')})
        except Exception as e:
            return JsonResponse({'answer': f"Connection Error: {str(e)}"})
            
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
    company = get_object_or_404(Company, id=company_id, user=request.user)
    employees = get_contacts_at_company_via_graph(company.id)
    
    return render(request, 'scanner/company.html', {
        'company': company,
        'employees': employees,
        'employee_count': len(employees)
    })

@login_required
def domain_network(request, domain_id):
    domain = get_object_or_404(Domain, id=domain_id, user=request.user)
    contacts = get_contacts_by_domain_via_graph(domain.id)
    
    return render(request, 'scanner/domain.html', {
        'domain': domain,
        'contacts': contacts,
        'contact_count': len(contacts)
    })

@login_required
def export_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="my_contacts.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['First Name', 'Last Name', 'Company', 'Email', 'Phone', 'Notes', 'Scanned Date'])
    
    cards = BusinessCard.objects.filter(user=request.user, is_approved=True).order_by('-scanned_at')
    for card in cards:
        writer.writerow([
            card.first_name,
            card.last_name,
            card.company_name,
            card.email,
            card.phone_number,
            card.manual_note,
            card.scanned_at.strftime("%Y-%m-%d")
        ])
    return response

def register_user(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('/dashboard/')
    else:
        form = UserCreationForm()
    return render(request, 'scanner/register.html', {'form': form})

def logout_user(request):
    logout(request)
    return redirect('/login/')