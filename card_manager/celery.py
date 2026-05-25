import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'card_manager.settings')

# Name the app
app = Celery('card_manager')

# Load settings from settings.py with the 'CELERY_' prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Automatically discover tasks in our Django apps
app.autodiscover_tasks()