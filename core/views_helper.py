from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from .models import Conversation, Interaction, ThinkingReview
from .services.deepseek_service import DeepSeekService
import json

@login_required
@csrf_exempt
def api_retry_last_message(request):
    """
    重试/补全最后一条未回复的用户消息
    """
    if request.method == 'POST':
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        conversation = get_object_or_404(Conversation, id=conversation_id, user=request.user)
        
        last_interaction = conversation.interactions.last()
        
        # 只有当最后一条消息是用户发出的，才需要重试
        if last_interaction and last_interaction.type in ['question', 'probe_answer', 'user_interpretation']:
            # 伪造一个 request.body 再次调用 api_send_message
            # 但我们需要稍微修改 api_send_message 逻辑，避免它重复创建用户消息
            # 简单起见，这里直接复用 api_send_message 的核心逻辑，或者重构
            
            # 由于 api_send_message 会先创建用户消息，直接调用会导致重复
            # 所以我们必须重构逻辑。
            # 方案：调用一个新的内部函数 _process_chat_logic，它接受 user_input 但不创建 Interaction
            
            user_input = last_interaction.text_content
            
            # 删除最后这条用户消息，因为它会在 _process_chat_logic 中被重新创建
            # 这是一个简单的 hack，避免大规模重构
            last_interaction.delete()
            
            # 构造新的 request 对象传递给 api_send_message
            # 或者更优雅地：将逻辑抽取出来。
            # 为了快速修复，我们抽取逻辑到 _handle_chat_response
            
            return _handle_chat_response(conversation, user_input)
            
        return JsonResponse({'status': 'no_need_to_retry'})
    return JsonResponse({'status': 'error'}, status=405)

from core.utils import save_uploaded_file

def _handle_chat_response(conversation, user_input, image_file=None):
    ai_service = DeepSeekService()
    
    # Check if image uploaded
    uploaded_image_url = None
    uploaded_image_path = None
    
    if image_file:
        uploaded_image_url, uploaded_image_path = save_uploaded_file(image_file)
    
    # Fallback text if only image provided
    if not user_input and uploaded_image_url:
        user_input = "[用户上传了一张图片]"
    
    # 1. Review 状态
    if conversation.status == 'review':
        return JsonResponse({'status': 'success', 'answer': '思考已完成。'})

    # 2. Initial Probe 状态
    if conversation.status == 'initial_probe':
        # 记录用户回答（问题）
        Interaction.objects.create(
            conversation=conversation, 
            type='question', 
            text_content=user_input,
            image_url=uploaded_image_url
        )
        
        # If user starts with image, we analyze it as initial probe?
        # Maybe just treat it as context.
        # But for now, let's keep it simple: just save it and proceed with standard flow.
        # Unless we want to use vision analysis to set the topic?
        
        if uploaded_image_path:
             # Analyze image to understand user intent/topic
             analysis = ai_service.analyze_image_content(uploaded_image_path, user_input)
             answer = f"我看到了你上传的图片。AI分析结果：{analysis}\n\n基于此，你有什么想进一步探讨的问题吗？"
        else:
            answer = ai_service.generate_initial_probe(user_input)
            if not answer:
                answer = "收到。关于这个问题，你现在有什么初步的想法或直觉吗？"
        
        Interaction.objects.create(conversation=conversation, type='ai_feedback', text_content=answer)
        
        conversation.status = 'visual_loop' 
        conversation.topic = user_input[:30]
        conversation.save()
        
        return JsonResponse({'status': 'success', 'answer': answer})
        
    # 3. Visual Loop 状态
    elif conversation.status == 'visual_loop':
        last_interaction = conversation.interactions.last()
        
        # 记录用户输入 (Unified here, removed duplicate creates below)
        user_interaction_type = 'probe_answer' if last_interaction and last_interaction.type == 'ai_feedback' else 'user_interpretation'
        
        # Avoid creating duplicate interaction if the function is called recursively or logically
        # But here we assume standard flow.
        
        # Create interaction ONLY if user_input is not empty (or image uploaded)
        # Check if we just created one? No, this is the main entry point for visual_loop.
        
        if user_input or uploaded_image_url:
            Interaction.objects.create(
                conversation=conversation, 
                type=user_interaction_type, 
                text_content=user_input,
                image_url=uploaded_image_url
            )

        if uploaded_image_path:
             # Analyze image
             analysis = ai_service.analyze_image_content(uploaded_image_path, user_input)
             Interaction.objects.create(conversation=conversation, type='ai_feedback', text_content=analysis)
             return JsonResponse({'status': 'success', 'answer': analysis})

        recent_interactions = conversation.interactions.all().order_by('-created_at')[:5]
        recent_interactions = reversed(recent_interactions)
        
        context = "\n".join([f"{i.type}: {i.text_content or i.image_prompt}" for i in recent_interactions])
        analysis = ai_service.analyze_user_input(conversation.topic, user_input, context)
        
        intent = analysis.get('intent')
        feedback = analysis.get('feedback', '')
        visual_prompt = analysis.get('visual_prompt')
        visual_guide_text = analysis.get('visual_guide_text')
        tool = analysis.get('tool', 'image_generation')

        # 记录用户输入
        # 注意：此处原逻辑有重复 create Interaction 的代码，我在这里进行修正。
        # 如果是递归调用或从 api_send_message 过来，已经在函数入口前处理或需要在这里处理？
        # 为了安全起见，我们假设 user_input 还没有被记录（如果函数头已经处理了，这里需要删除）
        # 但看上面的代码，user_input 确实没有在函数入口记录，而是在这里记录的。
        # 不过，上面的代码有两处记录 Interaction，这是一个 BUG。
        # 我会统一在 logic 开始处记录，或者根据 intent 记录。
        
        # 修正：删除之前的重复 create 代码，统一在这里处理
        # 逻辑：
        # 1. 记录用户的回答
        # 2. 如果 intent 是 probe_deeper，则返回文本引导
        # 3. 如果 intent 是 has_idea，则生成图片/Desmos
        
        # 之前代码里有两段 Interaction.objects.create，我把它们合并
        
        # 状态机处理
        if intent == 'probe_deeper':
             # 用户不知道，需要追问
             guide_text = visual_guide_text if visual_guide_text else "没关系。试着想象一下，如果我们改变一个条件..."
             Interaction.objects.create(conversation=conversation, type='ai_feedback', text_content=guide_text)
             return JsonResponse({'status': 'success', 'answer': guide_text})
             
        elif intent == 'no_idea' or intent == 'has_idea':
            # 只有 has_idea (或者 no_idea 的特殊情况) 才生图
            # 但根据新逻辑，no_idea 应该被 probe_deeper 捕获。除非模型坚持用 no_idea。
            # 这里兼容旧逻辑
            
            if tool == 'desmos':
                latex = analysis.get('desmos_latex', '')
                guide_text = visual_guide_text if visual_guide_text else "这是一个数学函数图像，试着调整参数看看会发生什么？"
                
                Interaction.objects.create(
                    conversation=conversation,
                    type='ai_image',
                    text_content=guide_text,
                    image_prompt=f"DESMOS: {latex}"
                )
                return JsonResponse({
                    'status': 'success', 
                    'answer': guide_text, 
                    'desmos_latex': latex
                })
            else:
                prompt = visual_prompt if visual_prompt else ai_service.generate_visual_prompt(conversation.topic, user_input if intent == 'has_idea' else "Concept of " + conversation.topic)
                image_url = ai_service.generate_image(prompt)
                guide_text = visual_guide_text if visual_guide_text else "这是一张为你生成的视觉线索图。请仔细观察它，你看到了什么？这与你的问题有什么联系？"

                Interaction.objects.create(
                    conversation=conversation,
                    type='ai_image',
                    image_url=image_url,
                    image_prompt=prompt,
                    text_content=guide_text
                )
                return JsonResponse({'status': 'success', 'answer': guide_text, 'image_url': image_url})

        elif intent == 'explaining_image':
            is_pass = analysis.get('evaluation') == 'pass'
            
            if is_pass:
                pass_count = conversation.interactions.filter(is_passed=True).count()
                
                if pass_count >= 2:
                    conversation.status = 'review'
                    conversation.is_completed = True
                    conversation.save()
                    
                    final_review = {
                        "summary": "你通过三张图片的联想，成功构建了问题的全貌。",
                        "thinking_path": [{"stage": "Done", "description": "Completed visual thinking."}],
                        "advice": "你的视觉联想能力很强。"
                    }
                    ThinkingReview.objects.create(
                        conversation=conversation,
                        summary_text=final_review['summary'],
                        thinking_path_json=final_review['thinking_path'],
                        advice_text=final_review['advice']
                    )
                    return JsonResponse({'status': 'success', 'answer': f"<FINAL_REVIEW>{json.dumps(final_review)}</FINAL_REVIEW>"})
                else:
                    Interaction.objects.filter(id=conversation.interactions.last().id).update(is_passed=True)
                    prompt = visual_prompt if visual_prompt else ai_service.generate_visual_prompt(conversation.topic, "Next step after: " + user_input)
                    image_url = ai_service.generate_image(prompt)
                    guide_text = visual_guide_text if visual_guide_text else "很有趣的解读。现在，让我们看看下一张图，它揭示了更深的一层含义..."

                    Interaction.objects.create(
                        conversation=conversation,
                        type='ai_image',
                        image_url=image_url,
                        image_prompt=prompt,
                        text_content=guide_text
                    )
                    return JsonResponse({'status': 'success', 'answer': guide_text, 'image_url': image_url})
            else:
                hint = analysis.get('next_step_hint', '请再仔细看看。')
                Interaction.objects.create(conversation=conversation, type='ai_feedback', text_content=hint)
                return JsonResponse({'status': 'success', 'answer': hint})

        else:
            Interaction.objects.create(conversation=conversation, type='ai_feedback', text_content="我不太理解。请试着描述图片与问题的关系。")
            return JsonResponse({'status': 'success', 'answer': "我不太理解..."})