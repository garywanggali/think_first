from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('ie-browser/', views.ie_browser, name='ie_browser'),
    path('signup/', views.signup, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('chat/', views.chat_view, name='chat_new'),
    path('chat/<int:conversation_id>/', views.chat_view, name='chat_detail'),
    path('chat/<int:conversation_id>/delete/', views.delete_conversation, name='delete_conversation'),
    path('api/send_message/', views.api_send_message, name='api_send_message'),
    path('api/retry/', views.api_retry_last_message, name='api_retry_last_message'), # 新增
]
