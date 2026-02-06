from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.db import models
from .models import Conversation, Interaction, ThinkingReview, UserProfile, Classroom
from .services.deepseek_service import DeepSeekService
import json

def index(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            if profile.role == 'teacher':
                return redirect('teacher_dashboard')
            # else student, fall through to index (or student dashboard)
        except UserProfile.DoesNotExist:
            # Create default profile if missing
            UserProfile.objects.create(user=request.user, role='student')
    
    # For students or anonymous
    return render(request, 'index.html')

def ie_browser(request):
    return render(request, 'ie_browser.html')

def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        role = request.POST.get('role', 'student')
        if form.is_valid():
            user = form.save()
            # Update Profile
            if hasattr(user, 'profile'):
                user.profile.role = role
                user.profile.save()
            else:
                UserProfile.objects.create(user=user, role=role)
                
            login(request, user)
            return redirect('index')
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form})

@login_required
def teacher_dashboard(request):
    # Ensure user is teacher
    if request.user.profile.role != 'teacher':
        return redirect('index')
    
    classes = request.user.teaching_classes.all().order_by('-created_at')
    
    return render(request, 'dashboard_teacher.html', {'classes': classes})

@login_required
def create_class(request):
    if request.method == 'POST' and request.user.profile.role == 'teacher':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        if name:
            Classroom.objects.create(teacher=request.user, name=name, description=description)
    return redirect('teacher_dashboard')

@login_required
def class_detail(request, class_id):
    if request.user.profile.role != 'teacher':
        return redirect('index')
        
    classroom = get_object_or_404(Classroom, id=class_id, teacher=request.user)
    students = classroom.students.all()
    
    # Simple Stats
    # Get all conversations from students in this class
    # Since we didn't force link conversations to class yet in existing data, 
    # we filter conversations by students.
    # Ideally, we should filter by conversation.classroom once implemented fully.
    # For now, let's get all conversations of these students.
    
    student_stats = []
    for s in students:
        convs = s.conversations.filter(classroom=classroom).order_by('-updated_at')
        if not convs.exists():
             # Fallback: check all convs if not explicitly linked (backward compatibility or loose mode)
             # But for strict class management, we should only show linked ones.
             # Let's show all for now but mark them.
             convs = s.conversations.all().order_by('-updated_at')
        
        stat = {
            'student': s,
            'conv_count': convs.count(),
            'last_active': convs.first().updated_at if convs.exists() else None,
            'topics': [c.topic for c in convs[:5]]
        }
        student_stats.append(stat)
        
    return render(request, 'class_detail.html', {'classroom': classroom, 'student_stats': student_stats})

@login_required
def join_class(request):
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        try:
            classroom = Classroom.objects.get(code=code)
            classroom.students.add(request.user)
            # Redirect to chat or home with success message
            return redirect('index')
        except Classroom.DoesNotExist:
            # Handle error
            pass
    return redirect('index')

@login_required
def chat_view(request, conversation_id=None):
    if conversation_id:
        conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
    else:
        # Check if student is in a class. If so, link the new conversation to the most recent class?
        # Or let user choose?
        # For MVP, if user is enrolled in classes, auto-link to the first one (or recently joined).
        
        # 查找是否存在未开始的空对话
        existing_empty_conv = Conversation.objects.filter(
            user=request.user, 
            status='initial_probe'
        ).annotate(count=models.Count('interactions')).filter(count__lte=1).first()
        
        if existing_empty_conv:
            conversation = existing_empty_conv
        else:
            # Create new
            classroom = None
            if request.user.profile.role == 'student':
                classroom = request.user.enrolled_classes.first()
            
            conversation = Conversation.objects.create(user=request.user, classroom=classroom)
            
            Interaction.objects.create(
                conversation=conversation,
                type='ai_feedback',
                text_content="你好。我是你的辅助思考助手。请告诉我，你遇到了哪道题？或者想弄懂什么概念？"
            )
    
    interactions = conversation.interactions.all().order_by('created_at')
    
    from django.conf import settings
    return render(request, 'book.html', {
        'conversation': conversation,
        'interactions': interactions,
        'desmos_api_key': settings.DESMOS_API_KEY
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

@login_required
@csrf_exempt
def api_rollback_conversation(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            conversation_id = data.get('conversation_id')
            interaction_id = data.get('interaction_id')
            
            conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
            target_interaction = get_object_or_404(Interaction, id=interaction_id, conversation=conversation)
            
            # Delete all interactions strictly AFTER the target
            # Note: We rely on created_at or id order. ID is safer for insertion order usually.
            Interaction.objects.filter(
                conversation=conversation,
                id__gt=target_interaction.id
            ).delete()
            
            # Reset status if needed
            if conversation.status == 'review' or conversation.is_completed:
                conversation.status = 'visual_loop'
                conversation.is_completed = False
                conversation.save()
                
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)
