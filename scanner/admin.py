from django.contrib import admin
from .models import BusinessCard, Company, Event, Task, KnowledgeEntity, KnowledgeRelationship, Domain, Opportunity

admin.site.register(BusinessCard)
admin.site.register(Company)
admin.site.register(Event)
admin.site.register(Task)
admin.site.register(KnowledgeEntity)
admin.site.register(KnowledgeRelationship)
admin.site.register(Domain)
admin.site.register(Opportunity)