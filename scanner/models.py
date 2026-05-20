from django.db import models
from django.contrib.auth.models import User

class BusinessCard(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='business_cards', null=True, blank=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    company_name = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=30, blank=True, null=True)
    manual_note = models.TextField(blank=True, null=True)
    card_image = models.ImageField(upload_to='cards/', blank=True, null=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name or 'Unknown'} {self.last_name or ''} - {self.company_name or 'No Company'}"