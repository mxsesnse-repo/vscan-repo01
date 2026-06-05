import datetime
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

def default_billing_date():
    return timezone.now().date() + datetime.timedelta(days=30)

class Company(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=True, null=True)
    normalized_name = models.CharField(max_length=255, db_index=True, blank=True, default="")
    website = models.CharField(max_length=255, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    company_type = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["normalized_name"]),
            models.Index(fields=["company_type"]),
        ]

    def __str__(self):
        return self.name or "Unnamed Company"

class Event(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, blank=True, null=True)
    event_type = models.CharField(max_length=100, blank=True, null=True)
    date = models.DateField(blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or "Unnamed Event"

class Domain(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name or "Unnamed Domain"

class BusinessCard(models.Model):
    CONTACT_TYPES = [
        ("customer", "Customer"),
        ("vendor", "Vendor"),
        ("investor", "Investor"),
        ("partner", "Partner"),
        ("research", "Research"),
        ("mentor", "Mentor"),
        ("government", "Government"),
        ("other", "Other"),
    ]
    
    RELATIONSHIP_STATUS = [
        ("prospect", "Prospect"),
        ("active", "Active"),
        ("dormant", "Dormant"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    designation = models.CharField(max_length=255, blank=True, null=True)
    contact_type = models.CharField(max_length=50, choices=CONTACT_TYPES, default="other")
    relationship_status = models.CharField(max_length=20, choices=RELATIONSHIP_STATUS, default="prospect")
    company_name = models.CharField(max_length=255, blank=True, null=True)
    company_link = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True, related_name="employees"
    )
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    website = models.CharField(max_length=255, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    manual_note = models.TextField(blank=True, null=True)
    card_image = models.ImageField(upload_to="cards/", blank=True, null=True)
    raw_ai_response = models.TextField(blank=True, null=True)
    extracted_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    is_duplicate = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_cards"
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    met_at_event = models.ForeignKey(
        Event, on_delete=models.SET_NULL, null=True, blank=True, related_name="contacts"
    )
    domains = models.ManyToManyField(Domain, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip()

    def __str__(self):
        return self.full_name or self.email or "Unnamed Contact"

class Interaction(models.Model):
    INTERACTION_TYPES = [
        ("call", "Call"),
        ("email", "Email"),
        ("meeting", "Meeting"),
    ]
    card = models.ForeignKey(BusinessCard, on_delete=models.CASCADE, related_name='interactions')
    type = models.CharField(max_length=20, choices=INTERACTION_TYPES)
    summary = models.TextField()
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_type_display()} - {self.card.full_name}"

class Task(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    contact = models.ForeignKey(BusinessCard, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255, blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or "Untitled Task"

class Opportunity(models.Model):
    STAGE_CHOICES = [
        ("lead", "Lead"),
        ("pitching", "Pitching"),
        ("negotiation", "Negotiation"),
        ("closed_won", "Closed Won"),
        ("closed_lost", "Closed Lost"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, blank=True, null=True)
    contact = models.ForeignKey(BusinessCard, on_delete=models.CASCADE, related_name="opportunities")
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default="lead")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or "Untitled Opportunity"

class KnowledgeEntity(models.Model):
    ENTITY_TYPES = [
        ("contact", "Contact"),
        ("company", "Company"),
        ("event", "Event"),
        ("domain", "Domain"),
        ("opportunity", "Opportunity"),
        ("task", "Task"),
        ("interaction", "Interaction"),
        ("document", "Document"),
        ("evidence", "Evidence"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("archived", "Archived"),
        ("merged", "Merged"),
    ]

    entity_type = models.CharField(max_length=50, choices=ENTITY_TYPES)
    source_table = models.CharField(max_length=100, default="")
    source_id = models.PositiveIntegerField()
    display_name = models.CharField(max_length=255)
    canonical_name = models.CharField(max_length=255, db_index=True, default="")
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="active")
    
    custom_tags = models.CharField(max_length=255, blank=True, null=True)
    priority_score = models.IntegerField(default=0)
    
    is_verified = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_entities"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["entity_type"]),
            models.Index(fields=["source_table", "source_id"]),
            models.Index(fields=["canonical_name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "source_table", "source_id"],
                name="unique_knowledge_entity"
            )
        ]

    def __str__(self):
        return f"{self.entity_type}: {self.display_name}"

class KnowledgeRelationship(models.Model):
    RELATIONSHIP_TYPES = [
        ("WORKS_AT", "Works At"),
        ("MET_AT", "Met At"),
        ("BELONGS_TO_DOMAIN", "Belongs To Domain"),
        ("DISCUSSED_USE_CASE", "Discussed Use Case"),
        ("LINKED_TO_OPPORTUNITY", "Linked To Opportunity"),
        ("HAS_INTERACTION", "Has Interaction"),
        ("HAS_TASK", "Has Task"),
        ("ASSIGNED_TO", "Assigned To"),
        ("DOCUMENT_SHARED_WITH", "Document Shared With"),
        ("SOURCE_EVIDENCE_OF", "Source Evidence Of"),
        ("SIMILAR_TO", "Similar To"),
        ("DUPLICATE_CANDIDATE_OF", "Duplicate Candidate Of"),
    ]

    source_entity = models.ForeignKey(
        KnowledgeEntity, related_name="outgoing_edges", on_delete=models.CASCADE
    )
    relationship_type = models.CharField(max_length=100, choices=RELATIONSHIP_TYPES)
    target_entity = models.ForeignKey(
        KnowledgeEntity, related_name="incoming_edges", on_delete=models.CASCADE
    )
    weight = models.FloatField(default=1.0)
    confidence = models.FloatField(default=1.0)
    source_type = models.CharField(max_length=100, blank=True, null=True)
    source_id = models.PositiveIntegerField(blank=True, null=True)
    is_verified = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_relationships"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["relationship_type"]),
            models.Index(fields=["source_entity", "relationship_type"]),
            models.Index(fields=["target_entity", "relationship_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_entity", "relationship_type", "target_entity"],
                name="unique_knowledge_relationship"
            )
        ]

class RelationshipEvidence(models.Model):
    relationship = models.ForeignKey(
        KnowledgeRelationship, related_name="evidence_items", on_delete=models.CASCADE
    )
    evidence_type = models.CharField(max_length=100)
    evidence_id = models.PositiveIntegerField(blank=True, null=True)
    evidence_excerpt = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class KnowledgeDocument(models.Model):
    ENTITY_TYPES = [
        ("contact", "Contact"),
        ("company", "Company"),
        ("event", "Event"),
        ("opportunity", "Opportunity"),
        ("task", "Task"),
        ("interaction", "Interaction"),
    ]
    INDEX_STATUS = [
        ("pending", "Pending"),
        ("indexed", "Indexed"),
        ("stale", "Stale"),
        ("failed", "Failed"),
    ]

    entity_type = models.CharField(max_length=50, choices=ENTITY_TYPES)
    entity_id = models.PositiveIntegerField()
    text_content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    source_hash = models.CharField(max_length=64, db_index=True)
    index_status = models.CharField(max_length=30, choices=INDEX_STATUS, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_indexed_at = models.DateTimeField(blank=True, null=True)

class DocumentChunk(models.Model):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_text = models.TextField()
    chunk_order = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class EmbeddingIndexMap(models.Model):
    chunk = models.OneToOneField(DocumentChunk, on_delete=models.CASCADE, related_name="embedding_map")
    vector_id = models.CharField(max_length=255, db_index=True)
    embedding_model = models.CharField(max_length=255)
    index_backend = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

class UserEmail(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='emails')
    email = models.EmailField(unique=True)
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.email} ({self.user.username})"

class UserPhone(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='phones')
    phone_number = models.CharField(max_length=20, unique=True)
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.phone_number} ({self.user.username})"

class Feedback(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField()
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class BillingProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='billing_profile')
    plan_name = models.CharField(max_length=100, default='Smart CRM Standard')
    next_billing_cycle = models.DateField(default=default_billing_date)
    has_paid = models.BooleanField(default=False)
    
    # NEW: Churn Tracking
    is_active = models.BooleanField(default=True)
    canceled_on = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {'Active' if self.is_active else 'Churned'}"

class Advertisement(models.Model):
    PLACEMENT_CHOICES = [
        ('dashboard_top', 'Dashboard Top Banner'),
        ('sidebar_right', 'Sidebar Advertisement'),
        ('email_blast', 'Email Newsletter Spot'),
        ('login_page', 'Login Page Feature'),
    ]
    
    ad_content = models.CharField(max_length=255)
    ad_file = models.FileField(upload_to='ads/')
    placement = models.CharField(max_length=50, choices=PLACEMENT_CHOICES)
    strategy = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    running_time = models.TimeField()
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # --- NEW TRACKING FIELDS ---
    clicks = models.IntegerField(default=0)
    impressions = models.IntegerField(default=0)
    avg_duration = models.FloatField(default=0.0) # Stored in seconds
    last_event = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.ad_content



class CustomerPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='ad_preferences')
    ad_tech = models.BooleanField(default=True)
    ad_finance = models.BooleanField(default=True)
    ad_marketing = models.BooleanField(default=False)
    ad_events = models.BooleanField(default=True)

class TransactionHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, default='Pending') # Can be 'Pending' or 'Paid'
    order_id = models.CharField(max_length=100, blank=True, null=True) 
    payment_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - {self.amount} - {self.status}"
    class Meta:
        ordering = ['-date']