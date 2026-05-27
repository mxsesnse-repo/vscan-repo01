from django.urls import path
from django.contrib.auth import views as auth_views
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
    path('export/', views.export_csv, name='export_csv'),
    
    path('register/', views.register_user, name='register'),
    path('logout/', views.logout_user, name='logout'),
    path('login/', auth_views.LoginView.as_view(template_name='scanner/login.html'), name='login'),
    path('domain/<int:domain_id>/', views.domain_network, name='domain_network'),
    path('add-domain/', views.add_domain, name='add_domain'),
    path('settings/', views.settings_view, name='settings'),
    path('settings/delete-domain/<int:domain_id>/', views.delete_domain, name='delete_domain'),
]