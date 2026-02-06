from django.db import models
from django.contrib.auth.models import User

class Conversation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversations')
    topic = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_completed = models.BooleanField(default=False)
    
    # 新增状态机字段
    STATUS_CHOICES = [
        ('initial_probe', '初始询问'),
        ('visual_loop', '视觉互动中'),
        ('review', '最终回顾')
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initial_probe')
    
    # 存储上下文摘要，用于 prompt
    context_summary = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - {self.topic[:20]}"

class Interaction(models.Model):
    INTERACTION_TYPES = [
        ('question', '用户提问'),
        ('probe_answer', '用户初始回答'),
        ('ai_image', 'AI生成图'),
        ('user_interpretation', '用户解读'),
        ('ai_feedback', 'AI反馈'),
        ('review', '最终回顾'),
    ]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='interactions')
    type = models.CharField(max_length=20, choices=INTERACTION_TYPES)
    
    # 内容字段
    text_content = models.TextField(blank=True, null=True) # 通用文本字段
    image_url = models.URLField(blank=True, null=True) # AI生成的图片URL
    image_prompt = models.TextField(blank=True, null=True) # 生成图片的Prompt
    
    # 状态标记
    is_passed = models.BooleanField(default=False, help_text="用户的解读是否通过验证")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.conversation.id} - {self.type}"

class ThinkingReview(models.Model):
    conversation = models.OneToOneField(Conversation, on_delete=models.CASCADE, related_name='review')
    summary_text = models.TextField()
    thinking_path_json = models.JSONField(help_text="用于前端绘制思维路径图的JSON数据")
    advice_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review for {self.conversation.id}"
