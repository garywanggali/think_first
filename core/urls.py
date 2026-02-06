from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('ie-browser/', views.ie_browser, name='ie_browser'),
    path('signup/', views.signup, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    
    # Teacher Dashboard
    path('dashboard/teacher/', views.teacher_dashboard, name='teacher_dashboard'),
    path('class/create/', views.create_class, name='create_class'),
    path('class/<int:class_id>/', views.class_detail, name='class_detail'),
    
    # Student Join
    path('class/join/', views.join_class, name='join_class'),
    
    path('chat/', views.chat_view, name='chat_new'),
    path('chat/<int:conversation_id>/', views.chat_view, name='chat_detail'),
    path('chat/<int:conversation_id>/delete/', views.delete_conversation, name='delete_conversation'),
    path('api/send_message/', views.api_send_message, name='api_send_message'),
    path('api/retry/', views.api_retry_last_message, name='api_retry_last_message'),
    path('api/rollback/', views.api_rollback_conversation, name='api_rollback_conversation'),
]
