from django.db import models
from django.contrib.auth.models import User

class Company(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Event(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    date = models.DateField(blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Domain(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class BusinessCard(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    company_link = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=50, blank=True, null=True)
    manual_note = models.TextField(blank=True, null=True)
    card_image = models.ImageField(upload_to='cards/', blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    is_duplicate = models.BooleanField(default=False)
    met_at_event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts')
    domains = models.ManyToManyField(Domain, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Task(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    contact = models.ForeignKey(BusinessCard, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=255)
    due_date = models.DateField(blank=True, null=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class Opportunity(models.Model):
    STAGE_CHOICES = [
        ("lead", "Lead"),
        ("pitching", "Pitching"),
        ("negotiation", "Negotiation"),
        ("closed_won", "Closed Won"),
        ("closed_lost", "Closed Lost"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    contact = models.ForeignKey(BusinessCard, on_delete=models.CASCADE, related_name='opportunities')
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default="lead")
    value = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

# --- KNOWLEDGE GRAPH MODELS ---

class KnowledgeEntity(models.Model):
    ENTITY_TYPES = [
        ("contact", "Contact"),
        ("company", "Company"),
        ("event", "Event"),
        ("domain", "Domain"),
        ("opportunity", "Opportunity"), # Added Opportunity
    ]
    
    entity_type = models.CharField(max_length=50, choices=ENTITY_TYPES)
    source_id = models.PositiveIntegerField()
    display_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["entity_type"]),
            models.Index(fields=["source_id"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["entity_type", "source_id"], name="unique_knowledge_entity")
        ]

    def __str__(self):
        return f"{self.entity_type}: {self.display_name}"

class KnowledgeRelationship(models.Model):
    RELATIONSHIP_TYPES = [
        ("WORKS_AT", "Works At"),
        ("MET_AT", "Met At"),
        ("BELONGS_TO_DOMAIN", "Belongs To Domain"),
        ("LINKED_TO_OPPORTUNITY", "Linked To Opportunity"), # Added Opportunity
    ]
    
    source_entity = models.ForeignKey(KnowledgeEntity, related_name="outgoing_edges", on_delete=models.CASCADE)
    relationship_type = models.CharField(max_length=100, choices=RELATIONSHIP_TYPES)
    target_entity = models.ForeignKey(KnowledgeEntity, related_name="incoming_edges", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source_entity", "relationship_type", "target_entity"], name="unique_knowledge_relationship")
        ]

class KnowledgeDocument(models.Model):
    ENTITY_TYPES = [("contact", "Contact"), ("company", "Company"), ("event", "Event")]
    INDEX_STATUS = [("pending", "Pending"), ("indexed", "Indexed"), ("stale", "Stale"), ("failed", "Failed")]
    
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