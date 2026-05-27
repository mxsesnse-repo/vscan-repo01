import json
import base64
import requests
import csv
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login, logout
from django.utils import timezone
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm

from .models import BusinessCard, Company, Event, Task, Domain, Opportunity, KnowledgeEntity, KnowledgeRelationship
from .graph_services import sync_card_to_graph, get_contacts_at_company_via_graph, get_contacts_by_domain_via_graph
from .tasks import process_business_card, index_contact_for_rag
from .rag_services import embed_text
from .vector_store import search_vectors

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

    entities = KnowledgeEntity.objects.filter(created_by=request.user)
    relationships = KnowledgeRelationship.objects.filter(created_by=request.user)

    nodes_list = []
    for entity in entities:
        nodes_list.append({
            "id": entity.id,
            "label": entity.display_name,
            "group": entity.entity_type 
        })

    edges_list = []
    for rel in relationships:
        pretty_label = rel.relationship_type.replace("_", " ").title() 
        edges_list.append({
            "from": rel.source_entity_id,
            "to": rel.target_entity_id,
            "label": pretty_label
        })

    graph_nodes_json = json.dumps(nodes_list)
    graph_edges_json = json.dumps(edges_list)

    context = {
        'cards': cards,
        'companies': companies,
        'tasks': tasks,
        'pending_cards': pending_cards,
        'total_contacts': total_contacts,
        'total_companies': total_companies,
        'pending_tasks': pending_tasks,
        'domains': domains,
        'opportunities': opportunities,
        'graph_nodes_json': graph_nodes_json, 
        'graph_edges_json': graph_edges_json  
    }
    return render(request, 'scanner/view.html', context)

@login_required
def approve_card(request, card_id):
    if request.method == 'POST':
        card = get_object_or_404(BusinessCard, id=card_id, user=request.user)

        is_dup = False
        if card.email:
            is_dup = BusinessCard.objects.filter(
                user=request.user, is_approved=True, email=card.email
            ).exclude(id=card.id).exists()
        if not is_dup and card.phone_number:
            is_dup = BusinessCard.objects.filter(
                user=request.user, is_approved=True, phone_number=card.phone_number
            ).exclude(id=card.id).exists()

        card.is_approved = True
        card.is_duplicate = is_dup
        card.reviewed_by = request.user
        card.reviewed_at = timezone.now()
        card.save()
        
        sync_card_to_graph(card, user=request.user)
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
        card.designation = request.POST.get('designation', '')
        card.contact_type = request.POST.get('contact_type', 'other')
        card.company_name = request.POST.get('company_name', '')
        card.email = request.POST.get('email', '')
        card.phone_number = request.POST.get('phone_number', '')
        card.website = request.POST.get('website', '')
        card.address = request.POST.get('address', '')
        card.manual_note = request.POST.get('manual_note', '')
        card.save()

        new_company_name = request.POST.get('company_name', '').strip()
        if new_company_name:
            company_obj, _ = Company.objects.get_or_create(
                user=request.user,
                name=new_company_name,
                defaults={"normalized_name": " ".join(new_company_name.lower().split())},
            )
            card.company_link = company_obj
            card.save(update_fields=['company_link'])
        
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
        
        sync_card_to_graph(card, user=request.user)
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

        sql_cards = BusinessCard.objects.filter(
            user=request.user, is_approved=True
        ).prefetch_related('opportunities', 'domains').select_related('company_link', 'met_at_event')

        sql_lines = []
        for card in sql_cards:
            line = (
                f"Contact: {card.full_name}, Designation: {card.designation or 'N/A'}, "
                f"Company: {card.company_name or 'N/A'}, Email: {card.email or 'N/A'}, "
                f"Phone: {card.phone_number or 'N/A'}, Notes: {card.manual_note or 'N/A'}"
            )
            for opp in card.opportunities.all():
                line += f" | Deal: {opp.title}, Stage: {opp.get_stage_display()}, Value: {opp.value}"
            sql_lines.append(line)

        vector_lines = []
        try:
            query_embedding = embed_text(user_message)
            vector_results = search_vectors(
                query_embedding=query_embedding,
                top_k=5,
                filters={"owner_id": request.user.id},
            )
            documents = vector_results.get("documents", [[]])[0]
            metadatas = vector_results.get("metadatas", [[]])[0]
            for doc, meta in zip(documents, metadatas):
                vector_lines.append(f"RAG Record: {doc} | Metadata: {meta}")
        except Exception:
            pass

        context_parts = []
        if sql_lines:
            context_parts.append("CRM Contacts:\n" + "\n".join(sql_lines))
        if vector_lines:
            context_parts.append("Semantic Search Results:\n" + "\n".join(vector_lines))

        context_data = "\n\n".join(context_parts) if context_parts else "No CRM records found."

        prompt = (
            "You are a CRM assistant.\n"
            "Answer the user's question using only the provided context.\n"
            "If the answer is not available in the context, say: "
            "\"I could not find this in the verified CRM records.\"\n\n"
            f"Context:\n{context_data}\n\n"
            f"Question:\n{user_message}\n\n"
            "Answer:"
        )

        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "llama3.2", "prompt": prompt, "stream": False},
                timeout=60,
            )
            return JsonResponse({'answer': response.json().get('response', 'Error.')})
        except Exception as exc:
            return JsonResponse({'answer': f"Connection Error: {str(exc)}"})

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

@login_required
def add_domain(request):
    if request.method == 'POST':
        domain_name = request.POST.get('domain_name', '').strip()
        if domain_name:
            Domain.objects.get_or_create(user=request.user, name=domain_name)
    return redirect('/dashboard/')

@login_required
def settings_view(request):
    domains = Domain.objects.filter(user=request.user).order_by('name')
    password_form = PasswordChangeForm(request.user)

    if request.method == 'POST':
        if 'update_profile' in request.POST:
            request.user.first_name = request.POST.get('first_name', '')
            request.user.last_name = request.POST.get('last_name', '')
            request.user.email = request.POST.get('email', '')
            request.user.save()
            return redirect('/settings/')
            
        elif 'change_password' in request.POST:
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                return redirect('/settings/')

    return render(request, 'scanner/settings.html', {
        'domains': domains,
        'password_form': password_form
    })

@login_required
def delete_domain(request, domain_id):
    if request.method == 'POST':
        domain = get_object_or_404(Domain, id=domain_id, user=request.user)
        domain.delete()
    return redirect('/settings/')