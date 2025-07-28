from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Main pages
    path('', views.welcome, name='welcome'),
    path('register/', views.register, name='register'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('quests/', views.quests, name='quests'),
    path('stats/', views.stats, name='stats'),
    path('chat/', views.chat, name='chat'),
    path('settings/', views.settings, name='settings'),
    
    # Authentication URLs
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        redirect_authenticated_user=True
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    # HTMX API endpoints
    path('api/complete-quest/<int:quest_id>/', views.complete_quest, name='complete_quest'),
    path('api/refresh-stats/', views.refresh_stats, name='refresh_stats'),
    path('api/generate-quests/', views.generate_new_quests, name='generate_quests'),
] 