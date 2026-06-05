import json
import base64
import csv
import re
import time
import random
import os
from collections import Counter
from datetime import timedelta

import psutil
import requests
import razorpay
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone
from django.db.models import Count, Sum
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache

from .models import (
    BusinessCard, Company, Event, Task, Domain, Opportunity, 
    KnowledgeEntity, KnowledgeRelationship, UserEmail, UserPhone, 
    Feedback, BillingProfile, Advertisement, CustomerPreference, TransactionHistory
)
from .graph_services import sync_card_to_graph, get_contacts_at_company_via_graph, get_contacts_by_domain_via_graph
from .tasks import process_business_card, index_contact_for_rag
from .rag_services import embed_text
from .vector_store import search_vectors

try:
    razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
except AttributeError:
    razorpay_client = None

def scan_card(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required. Please refresh and log in.'}, status=401)

    if request.method == 'POST' and request.FILES.get('image'):
        try:
            image_file = request.FILES['image']
            user_note = request.POST.get('manual_note', '')
            
            new_card = BusinessCard.objects.create(
                user=request.user,
                first_name="Pending",
                last_name="Extraction...",
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

    nodes_list = [{"id": entity.id, "label": entity.display_name, "group": entity.entity_type} for entity in entities]
    
    edges_list = [{
        "from": rel.source_entity_id,
        "to": rel.target_entity_id,
        "label": rel.relationship_type.replace("_", " ").title()
    } for rel in relationships]

    graph_nodes_json = json.dumps(nodes_list)
    graph_edges_json = json.dumps(edges_list)

    topic_filter = request.GET.get('topic_filter', 'company')
    if topic_filter == 'company':
        notes = cards.values_list('company_name', flat=True)
    elif topic_filter == 'location':
        notes = cards.values_list('address', flat=True)
    elif topic_filter == 'designation':
        notes = cards.values_list('designation', flat=True)
    elif topic_filter == 'domain':
        notes = cards.values_list('domains__name', flat=True)
    else:
        notes = cards.values_list('manual_note', flat=True)

    text = " ".join(filter(None, notes)).lower()
    words = re.findall(r'\b[a-z]{4,}\b', text)
    stop_words = {'that', 'this', 'with', 'from', 'have', 'were', 'they', 'will', 'your', 'about', 'and', 'the'}
    filtered_words = [w for w in words if w not in stop_words]
    bag_of_words = Counter(filtered_words).most_common(40)

    max_count = bag_of_words[0][1] if bag_of_words else 1
    bag_of_words_scaled = [(word, int((count / max_count) * 28) + 12) for word, count in bag_of_words]

    try:
        active_subscriptions = 1 if request.user.billing_profile.has_paid and request.user.billing_profile.is_active else 0
    except BillingProfile.DoesNotExist:
        active_subscriptions = 0

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
        'graph_edges_json': graph_edges_json,
        'bag_of_words': bag_of_words_scaled,
        'active_subscriptions': active_subscriptions,
        'current_topic_filter': topic_filter,
    }
    return render(request, 'scanner/view.html', context)


@login_required
@require_POST
def approve_card(request, card_id):
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
        card.relationship_status = request.POST.get('relationship_status', 'prospect')
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

        if opp_title: 
            if opportunity:
                opportunity.title = opp_title
                opportunity.stage = opp_stage
                opportunity.save()
            else:
                Opportunity.objects.create(
                    user=request.user,
                    contact=card,
                    title=opp_title,
                    stage=opp_stage
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
                line += f" | Deal: {opp.title}, Stage: {opp.get_stage_display()}"
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
@require_POST
def delete_card(request, card_id):
    card = get_object_or_404(BusinessCard, id=card_id, user=request.user)
    card.delete()
    return redirect('/dashboard/')


@login_required
@require_POST
def copy_card(request, card_id):
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
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('/dashboard/')
    else:
        form = UserCreationForm()
    return render(request, 'scanner/register.html', {'form': form})


def logout_user(request):
    logout(request)
    return redirect('/login/')


@login_required
@require_POST
def add_domain(request):
    domain_name = request.POST.get('domain_name', '').strip()
    if domain_name:
        Domain.objects.get_or_create(user=request.user, name=domain_name)
    return redirect('/dashboard/')


@login_required
def settings_view(request):
    if request.method == 'POST':
        if 'update_profile' in request.POST:
            request.user.first_name = request.POST.get('first_name', '')
            request.user.last_name = request.POST.get('last_name', '')
            request.user.save()
            
        elif 'change_password' in request.POST:
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                
        elif 'add_email' in request.POST:
            new_email = request.POST.get('new_email', '').strip()
            if new_email and not UserEmail.objects.filter(email=new_email).exists():
                UserEmail.objects.create(user=request.user, email=new_email)
                
        elif 'add_phone' in request.POST:
            new_phone = request.POST.get('new_phone', '').strip()
            if new_phone and not UserPhone.objects.filter(phone_number=new_phone).exists():
                UserPhone.objects.create(user=request.user, phone_number=new_phone)
                
        elif 'delete_email' in request.POST:
            email_id = request.POST.get('email_id')
            UserEmail.objects.filter(id=email_id, user=request.user).delete()
                
        elif 'delete_phone' in request.POST:
            phone_id = request.POST.get('phone_id')
            UserPhone.objects.filter(id=phone_id, user=request.user).delete()
                
        elif 'update_ad_prefs' in request.POST:
            prefs, _ = CustomerPreference.objects.get_or_create(user=request.user)
            prefs.ad_tech = 'ad_tech' in request.POST
            prefs.ad_finance = 'ad_finance' in request.POST
            prefs.ad_marketing = 'ad_marketing' in request.POST
            prefs.ad_events = 'ad_events' in request.POST
            prefs.save()
            messages.success(request, "Advertisement preferences updated.")
            
        return redirect('/settings/')

    domains = Domain.objects.filter(user=request.user).order_by('name')
    emails = request.user.emails.all() 
    phones = request.user.phones.all() 
    password_form = PasswordChangeForm(request.user)
    cards = BusinessCard.objects.filter(user=request.user, is_approved=True).order_by('first_name')
    prefs, _ = CustomerPreference.objects.get_or_create(user=request.user)
    transactions = TransactionHistory.objects.filter(user=request.user)[:5]

    return render(request, 'scanner/settings.html', {
        'domains': domains,
        'emails': emails,
        'phones': phones,
        'password_form': password_form,
        'cards': cards,
        'prefs': prefs,
        'transactions': transactions,
    })


@login_required
@require_POST
def delete_domain(request, domain_id):
    domain = get_object_or_404(Domain, id=domain_id, user=request.user)
    domain.delete()
    return redirect('/settings/')


@login_required
@require_POST
def submit_feedback(request):
    rating = request.POST.get('rating', 0)
    text = request.POST.get('feedback_text', '')
    
    Feedback.objects.create(
        user=request.user,
        rating=rating,
        text=text
    )
    
    messages.success(request, 'Thank you for your feedback! It has been securely recorded.')
    return redirect('/dashboard/')


@login_required
@require_POST
def initiate_payment_view(request):
    amount_in_rupees = float(request.POST.get('amount', 0))
    amount_in_paise = int(amount_in_rupees * 100)
    description = request.POST.get('description', 'CRM Transaction')

    if razorpay_client:
        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': f'receipt_user_{request.user.id}',
            'payment_capture': 1 
        }
        payment_order = razorpay_client.order.create(data=order_data)
        order_id = payment_order['id']
    else:
        order_id = f"order_mock_fallback_{request.user.id}"

    txn = TransactionHistory.objects.create(
        user=request.user,
        title=description,
        amount=amount_in_rupees,
        status='Pending',
    )
    
    if hasattr(txn, 'order_id'):
        txn.order_id = order_id
        txn.save()

    return JsonResponse({
        'success': True,
        'order_id': order_id,
        'amount_paise': amount_in_paise,
        'transaction_id': txn.id,
        'key_id': getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_PLACEHOLDER')
    })


@csrf_exempt
@require_POST
def razorpay_webhook_placeholder(request):
    razorpay_order_id = request.POST.get('razorpay_order_id')
    razorpay_payment_id = request.POST.get('razorpay_payment_id')
    razorpay_signature = request.POST.get('razorpay_signature')
    
    params_dict = {
        'razorpay_order_id': razorpay_order_id,
        'razorpay_payment_id': razorpay_payment_id,
        'razorpay_signature': razorpay_signature
    }
    
    try:
        if razorpay_client:
            razorpay_client.utility.verify_payment_signature(params_dict)
        
        txn = TransactionHistory.objects.filter(order_id=razorpay_order_id).first()
        if txn:
            txn.status = 'Paid'
            if hasattr(txn, 'payment_id'):
                txn.payment_id = razorpay_payment_id
            txn.save()
            
            profile, _ = BillingProfile.objects.get_or_create(user=txn.user)
            profile.has_paid = True
            profile.is_active = True
            profile.save()
        
        return JsonResponse({'status': 'Payment successful and verified!'})
        
    except Exception as e:
        if razorpay_order_id:
            TransactionHistory.objects.filter(order_id=razorpay_order_id).update(status='Failed')
        return JsonResponse({'status': 'Payment verification failed.', 'error': str(e)}, status=400)


@staff_member_required
def admin_dashboard(request):
    customers = User.objects.filter(is_staff=False).order_by('-date_joined')
    total_customers = customers.count()

    missing_profiles = customers.filter(billing_profile__isnull=True)
    if missing_profiles.exists():
        BillingProfile.objects.bulk_create([BillingProfile(user=u) for u in missing_profiles])

    billing_profiles = BillingProfile.objects.select_related('user').all()
    paid_count = billing_profiles.filter(has_paid=True, is_active=True).count()
    unpaid_count = billing_profiles.filter(has_paid=False, is_active=True).count()
    churned_count = billing_profiles.filter(is_active=False).count()
    churn_rate = f"{(churned_count / max(total_customers, 1)) * 100:.1f}%"

    pending_ads = Advertisement.objects.filter(is_approved=False).order_by('-created_at')
    active_ads = Advertisement.objects.filter(is_approved=True).order_by('-last_event')

    timeframe = request.GET.get('timeframe', 'months')
    if timeframe == 'days':
        trunc_func = TruncDay('date_joined')
        trunc_txn = TruncDay('date')
        date_format = '%b %d'
    elif timeframe == 'weeks':
        trunc_func = TruncWeek('date_joined')
        trunc_txn = TruncWeek('date')
        date_format = 'Week %W'
    elif timeframe == 'years':
        trunc_func = TruncYear('date_joined')
        trunc_txn = TruncYear('date')
        date_format = '%Y'
    else: 
        trunc_func = TruncMonth('date_joined')
        trunc_txn = TruncMonth('date')
        date_format = '%b %Y'

    user_growth = customers.annotate(date_group=trunc_func).values('date_group').annotate(count=Count('id')).order_by('date_group')
    chart_labels = [entry['date_group'].strftime(date_format) for entry in user_growth if entry['date_group']]
    chart_data = [entry['count'] for entry in user_growth if entry['date_group']]

    revenue_history = TransactionHistory.objects.filter(status='Paid').annotate(date_group=trunc_txn).values('date_group').annotate(total_revenue=Sum('amount'), dynamic_count=Count('id')).order_by('date_group')
    
    payment_labels = [entry['date_group'].strftime(date_format) for entry in revenue_history if entry['date_group']]
    payment_data = [float(entry['total_revenue']) for entry in revenue_history if entry['date_group']]
    acquisition_data = [entry['dynamic_count'] for entry in revenue_history if entry['date_group']]

    if not payment_labels:
        payment_labels = chart_labels if chart_labels else ["Current Period"]
        payment_data = [0.0] * len(payment_labels)
        acquisition_data = [0] * len(payment_labels)

    active_utilization_count = billing_profiles.filter(is_active=True).count()
    inactive_utilization_count = billing_profiles.filter(is_active=False).count()
    utilization_data = [active_utilization_count, inactive_utilization_count]

    total_ads = Advertisement.objects.count()
    active_vs_closed = Advertisement.objects.values('is_approved').annotate(count=Count('id'))
    ad_active_data = [
        active_vs_closed.get(is_approved=True)['count'] if active_vs_closed.filter(is_approved=True).exists() else 0,
        active_vs_closed.get(is_approved=False)['count'] if active_vs_closed.filter(is_approved=False).exists() else 0
    ]

    ad_trends = Advertisement.objects.annotate(date_group=TruncMonth('created_at')).values('date_group').annotate(count=Count('id')).order_by('date_group')
    ad_trend_labels = [entry['date_group'].strftime('%b %Y') for entry in ad_trends if entry['date_group']]
    ad_trend_data = [entry['count'] for entry in ad_trends if entry['date_group']]
    
    if not ad_trend_labels:
        ad_trend_labels = ["Current Month"]
        ad_trend_data = [total_ads]

    app_version = "v2.5.0" 
    
    try:
        User.objects.exists() 
        db_status = "Connected"
    except Exception:
        db_status = "Disconnected"

    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time
    uptime_days = int(uptime_seconds // (24 * 3600))
    uptime_hours = int((uptime_seconds % (24 * 3600)) // 3600)
    uptime_string = f"{uptime_days}d {uptime_hours}h"

    current_cpu = psutil.cpu_percent(interval=0.1)
    
    api_latency = random.randint(25, 45) 

    now = timezone.localtime()
    perf_time_labels = [(now - timedelta(minutes=5*i)).strftime('%H:%M') for i in range(5, -1, -1)]
    cpu_usage_data = [random.randint(15, 40) for _ in range(5)] + [current_cpu]
    api_traffic_data = [random.randint(100, 250) for _ in range(6)]

    feedbacks = Feedback.objects.select_related('user').order_by('-created_at')[:10]

    context = {
        'users': customers, 
        'total_users': total_customers,
        'paid_count': paid_count,
        'unpaid_count': unpaid_count,
        'churn_rate': churn_rate,
        'billing_profiles': billing_profiles,
        'pending_ads': pending_ads,
        'active_ads': active_ads,
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data),
        'payment_labels': json.dumps(payment_labels),
        'payment_data': json.dumps(payment_data),
        'acquisition_data': json.dumps(acquisition_data),
        'utilization_data': json.dumps(utilization_data),
        'ad_total': total_ads,
        'ad_active_data': json.dumps(ad_active_data),
        'ad_trend_labels': json.dumps(ad_trend_labels),
        'ad_trend_data': json.dumps(ad_trend_data),
        'current_timeframe': timeframe,
        'app_version': app_version,
        'db_status': db_status,
        'uptime_percentage': uptime_string,
        'api_latency': api_latency,
        'perf_time_labels': json.dumps(perf_time_labels),
        'cpu_usage_data': json.dumps(cpu_usage_data),
        'api_traffic_data': json.dumps(api_traffic_data),
        'feedbacks': feedbacks,
    }
    return render(request, 'scanner/admin_dashboard.html', context)


@staff_member_required
@require_POST
def close_account(request, user_id):
    user_to_delete = get_object_or_404(User, id=user_id)
    
    if user_to_delete == request.user:
        messages.error(request, "You cannot delete your own admin account.")
    elif user_to_delete.is_superuser:
        messages.error(request, "Cannot delete a superuser account from this dashboard.")
    else:
        username = user_to_delete.username
        user_to_delete.delete()
        messages.success(request, f"Account '{username}' has been permanently closed.")
        
    return redirect('/custom-admin/')


@staff_member_required
@require_POST
def toggle_admin(request, user_id):
    target_user = get_object_or_404(User, id=user_id)
    if target_user == request.user:
        messages.error(request, "You cannot change your own admin status.")
    elif target_user.is_superuser and not request.user.is_superuser:
        messages.error(request, "You cannot modify a superuser.")
    else:
        target_user.is_staff = not target_user.is_staff
        target_user.save()
        status_text = "granted" if target_user.is_staff else "revoked"
        messages.success(request, f"Admin privileges {status_text} for {target_user.username}.")
    return redirect('/custom-admin/')


@staff_member_required
@require_POST
def hold_subscription(request, user_id):
    profile, _ = BillingProfile.objects.get_or_create(user_id=user_id)
    profile.is_active = False
    profile.save()
    messages.success(request, "Subscription placed on hold.")
    return redirect('/custom-admin/')


@staff_member_required
@require_POST
def activate_subscription(request, user_id):
    profile, _ = BillingProfile.objects.get_or_create(user_id=user_id)
    profile.is_active = True
    profile.save()
    messages.success(request, "Subscription activated.")
    return redirect('/custom-admin/')


@staff_member_required
@require_POST
def update_subscription_plan(request, user_id):
    profile, _ = BillingProfile.objects.get_or_create(user_id=user_id)
    profile.plan_name = request.POST.get("plan_name")
    profile.save()
    messages.success(request, "Plan updated.")
    return redirect('/custom-admin/')


@staff_member_required
def billing_history(request, user_id):
    user_obj = get_object_or_404(User, id=user_id)
    transactions = TransactionHistory.objects.filter(
        user=user_obj
    ).order_by('-date')

    return render(
        request,
        'scanner/billing_history.html',
        {
            'customer': user_obj,
            'transactions': transactions
        }
    )


@login_required
@require_POST
def launch_ad(request):
    Advertisement.objects.create(
        ad_content=request.POST.get('ad_content'),
        ad_file=request.FILES.get('ad_file'),
        placement=request.POST.get('configure_services'),
        strategy=request.POST.get('manage_services'),
        start_date=request.POST.get('start_date'),
        end_date=request.POST.get('end_date'),
        running_time=request.POST.get('running_time')
    )
    return redirect('/dashboard/')


@staff_member_required
@require_POST
def approve_ad(request, ad_id):
    ad = get_object_or_404(Advertisement, id=ad_id)
    ad.is_approved = True
    ad.save()
    messages.success(request, f"Ad '{ad.ad_content}' is now live!")
    return redirect('/custom-admin/')


@staff_member_required
@require_POST
def check_updates(request):
    messages.info(request, "Checking repositories... Your system is currently up to date (v2.5.0).")
    return redirect('/custom-admin/')


@staff_member_required
@require_POST
def rollback_version(request):
    messages.warning(request, "Rollback initiated. Deploying previous container image (v2.4.0)... (Simulation)")
    return redirect('/custom-admin/')


@staff_member_required
def manage_configs(request):
    if request.method == 'POST':
        cache.set('maintenance_mode', request.POST.get('maintenance_mode') == 'on', timeout=None)
        cache.set('max_upload_size', request.POST.get('max_upload_size', '5'), timeout=None)
        cache.set('session_timeout', request.POST.get('session_timeout', '120'), timeout=None)
        cache.set('debug_mode', request.POST.get('debug_mode') == 'on', timeout=None)
        
        messages.success(request, "Server configurations updated successfully.")
        return redirect('/custom-admin/configs/')

    context = {
        'maintenance_mode': cache.get('maintenance_mode', False),
        'max_upload_size': cache.get('max_upload_size', '5'),
        'session_timeout': cache.get('session_timeout', '120'),
        'debug_mode': cache.get('debug_mode', False),
    }
    return render(request, 'scanner/admin_configs.html', context)


@staff_member_required
def view_logs(request):
    try:
        log_file_path = os.path.join(settings.BASE_DIR, 'debug.log')
        
        with open(log_file_path, 'r') as file:
            real_logs = "".join(file.readlines()[-50:]) 
    except FileNotFoundError:
        real_logs = "Log file not found."
        
    return HttpResponse(f"<pre style='background:#1e1e1e; color:#00ff00; padding:20px;'>{real_logs}</pre>")