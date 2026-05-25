from .models import BusinessCard, Company, Event, KnowledgeEntity, KnowledgeRelationship

def normalize_name(value):
    if not value:
        return ""
    return "".join(value.lower().strip().split())

def get_or_create_entity(entity_type, source_id, display_name):
    # We remove 'canonical_name' because it's not in your model/table
    entity, created = KnowledgeEntity.objects.get_or_create(
        entity_type=entity_type,
        source_id=source_id,
        defaults={
            "display_name": display_name or "Unnamed",
            # If you need to store the normalized name, 
            # make sure this field exists in your models.py first.
            # If not, just remove this line.
        }
    )
    return entity

def create_or_update_relationship(source_entity, relationship_type, target_entity):
    relationship, created = KnowledgeRelationship.objects.get_or_create(
        source_entity=source_entity,
        relationship_type=relationship_type,
        target_entity=target_entity,
    )
    return relationship

def sync_card_to_graph(card):
    contact_name = f"{card.first_name} {card.last_name}".strip()
    contact_entity = get_or_create_entity("contact", card.id, contact_name)

    # 1. Link Company
    if card.company_link:
        company_entity = get_or_create_entity("company", card.company_link.id, card.company_link.name)
        create_or_update_relationship(contact_entity, "WORKS_AT", company_entity)

    # 2. Link Event
    if hasattr(card, 'met_at_event') and card.met_at_event:
        event_entity = get_or_create_entity("event", card.met_at_event.id, card.met_at_event.name)
        create_or_update_relationship(contact_entity, "MET_AT", event_entity)
        
    # 3. Link Domain Tags
    for domain in card.domains.all():
        domain_entity = get_or_create_entity("domain", domain.id, domain.name)
        create_or_update_relationship(contact_entity, "BELONGS_TO_DOMAIN", domain_entity)
        
    # 4. Link Opportunities (Requirement from Phase 5 Blueprint)
    for opp in card.opportunities.all():
        opp_entity = get_or_create_entity("opportunity", opp.id, opp.title)
        create_or_update_relationship(contact_entity, "LINKED_TO_OPPORTUNITY", opp_entity)
        
    return contact_entity

def get_contacts_at_company_via_graph(company_id):
    try:
        company_entity = KnowledgeEntity.objects.get(
            entity_type="company", 
            source_id=company_id
        )
    except KnowledgeEntity.DoesNotExist:
        return BusinessCard.objects.none()

    relationships = KnowledgeRelationship.objects.filter(
        relationship_type="WORKS_AT",
        target_entity=company_entity,
        source_entity__entity_type="contact"
    ).select_related("source_entity")

    contact_ids = [rel.source_entity.source_id for rel in relationships]
    return BusinessCard.objects.filter(id__in=contact_ids, is_approved=True).order_by('-scanned_at')

def get_contacts_by_domain_via_graph(domain_id):
    try:
        domain_entity = KnowledgeEntity.objects.get(
            entity_type="domain", 
            source_id=domain_id
        )
    except KnowledgeEntity.DoesNotExist:
        return BusinessCard.objects.none()

    relationships = KnowledgeRelationship.objects.filter(
        relationship_type="BELONGS_TO_DOMAIN",
        target_entity=domain_entity,
        source_entity__entity_type="contact"
    ).select_related("source_entity")

    contact_ids = [rel.source_entity.source_id for rel in relationships]
    return BusinessCard.objects.filter(id__in=contact_ids, is_approved=True).order_by('-scanned_at')