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
    path('submit-feedback/', views.submit_feedback, name='submit_feedback'),
    path('custom-admin/', views.admin_dashboard, name='admin_dashboard'),
    path('custom-admin/close-account/<int:user_id>/', views.close_account, name='close_account'),
    path('custom-admin/toggle-admin/<int:user_id>/', views.toggle_admin, name='toggle_admin'),
    path('custom-admin/hold-subscription/<int:user_id>/', views.hold_subscription, name='hold_subscription'),
    path('custom-admin/activate-subscription/<int:user_id>/', views.activate_subscription, name='activate_subscription'),
    path('custom-admin/update-plan/<int:user_id>/', views.update_subscription_plan, name='update_subscription_plan'),
    path('custom-admin/billing-history/<int:user_id>/', views.billing_history, name='billing_history'),
    path('submit-ad/', views.launch_ad, name='launch_ad'),
    path('custom-admin/ads/approve/<int:ad_id>/', views.approve_ad, name='approve_ad'),
    path('custom-admin/check-updates/', views.check_updates, name='check_updates'),
    path('custom-admin/logs/', views.view_logs, name='view_logs'),
    path('custom-admin/rollback/', views.rollback_version, name='rollback_version'),
    path('custom-admin/configs/', views.manage_configs, name='manage_configs'),
]