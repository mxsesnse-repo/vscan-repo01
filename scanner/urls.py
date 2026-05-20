from django.urls import path
from . import views

urlpatterns = [
    path('', views.scan_card, name='scan_card'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('edit/<int:card_id>/', views.edit_card, name='edit_card'),
    path('chat/', views.chat_view, name='chat'),
    path('delete/<int:card_id>/', views.delete_card, name='delete_card'),
    path('copy/<int:card_id>/', views.copy_card, name='copy_card'),
    path('approve/<int:card_id>/', views.approve_card, name='approve_card'),
    path('company/<int:company_id>/', views.company_network, name='company_network'),
]