from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.db import models
from .models import Conversation, Interaction, ThinkingReview
from .services.deepseek_service import DeepSeekService
import json

def index(request):
    return render(request, 'index.html')

def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('index')
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form})

@login_required
def chat_view(request, conversation_id=None):
    if conversation_id:
        conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
    else:
        # 查找是否存在未开始的空对话（没有 interactions 或 仅有初始 AI 引导）
        # 这里的判断标准是：status='initial_probe' 且 interactions 数量 <= 1 (只有系统自动发的欢迎语)
        existing_empty_conv = Conversation.objects.filter(
            user=request.user, 
            status='initial_probe'
        ).annotate(count=models.Count('interactions')).filter(count__lte=1).first()
        
        if existing_empty_conv:
            conversation = existing_empty_conv
        else:
            # 新建 Conversation
            conversation = Conversation.objects.create(user=request.user)
            # 立即创建一个初始引导 Interaction
            Interaction.objects.create(
                conversation=conversation,
                type='ai_feedback',
                text_content="欢迎来到视觉思考空间。请告诉我，你想要解决什么问题？"
            )
    
    interactions = conversation.interactions.all().order_by('created_at')
    
    return render(request, 'chat.html', {
        'conversation': conversation,
        'interactions': interactions
    })

@login_required
@csrf_exempt
def delete_conversation(request, conversation_id):
    if request.method == 'POST':
        conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
        conversation.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

from .views_helper import _handle_chat_response, api_retry_last_message

@login_required
@csrf_exempt
def api_send_message(request):
    if request.method == 'POST':
        # Check if it's multipart/form-data or JSON
        if request.content_type.startswith('multipart/form-data') or request.FILES:
            conversation_id = request.POST.get('conversation_id')
            user_input = request.POST.get('query')
            image_file = request.FILES.get('image')
        else:
            # Fallback for JSON (e.g. from existing logic or tests)
            try:
                data = json.loads(request.body)
                conversation_id = data.get('conversation_id')
                user_input = data.get('query')
                image_file = None
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        
        conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
        
        return _handle_chat_response(conversation, user_input, image_file)
            
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)
