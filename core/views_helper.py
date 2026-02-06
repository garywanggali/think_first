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
    
    # --- DEMO MODE CHECK ---
    # Check for "Relativity Demo" trigger
    # Trigger 1: Explicit command "广义相对论是什么？"
    # Trigger 2: User asks specifically about "引力" or "相对论" as the FIRST question
    is_demo_trigger = False
    if "广义相对论是什么" in user_input.replace("？", "").replace("?", ""):
        is_demo_trigger = True
        user_input = "为什么会有引力？" # Normalize input for demo start
    elif conversation.interactions.count() <= 1 and ("引力" in user_input or "相对论" in user_input):
        # Only auto-trigger on first interaction
        is_demo_trigger = True
    
    # If we are already IN a demo sequence (conversation marked as demo), continue the script
    # We can use a special topic prefix like "[DEMO] Relativity" to track state
    if is_demo_trigger or conversation.topic.startswith("[DEMO]"):
        return _handle_relativity_demo(conversation, user_input, is_demo_trigger, uploaded_image_url)
    # -----------------------

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
             guide_text = visual_guide_text
             
             # 如果 guide_text 为空，或者是一个机械的默认回复，我们需要处理
             # 但更好的策略是：如果 DeepSeek 返回 probe_deeper，它应该已经生成了一个针对性的问题在 visual_guide_text 中
             # 如果 visual_guide_text 是空的，说明 DeepSeek 没有正确遵循 JSON 格式返回 'visual_guide_text'
             
             if not guide_text or guide_text == "没关系。试着想象一下，如果我们改变一个条件...":
                 # 强制让 DeepSeek 生成一个具体的、针对上下文的引导问题
                 # 这里我们再次调用 DeepSeek 生成一个简单的文本引导
                 prompt = f"""
                 Context: User says "{user_input}" (indicating they don't know).
                 Current Topic: {conversation.topic}
                 Task: Ask a simple, intuitive question to help them guess. 
                 Do NOT say "Never mind" or "Let's imagine". Just ask the question directly.
                 Example: "What do you think happens if...?"
                 Language: Chinese.
                 """
                 messages = [{"role": "user", "content": prompt}]
                 guide_text = ai_service.chat_completion(messages)

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

        elif intent == 'verify_understanding':
            # AI wants to verify understanding with a Fill-in-the-Blank challenge
            fill_data = analysis.get('fill_in_the_blank', {})
            guide_text = visual_guide_text if visual_guide_text else "看来你已经抓住关键了。来做一个小测试验证一下你的理解。"
            
            # Save fill-in-the-blank data into interaction metadata (text_content will store JSON string or we add a field)
            # For simplicity, we embed it in text_content with a special marker or just return it in JSON response
            # But we need to save it to history.
            # Let's use a special prefix or just save the guide text, and frontend handles the interactive part if it's live.
            # But if we reload page, we need the data.
            # So, we should store it. Let's assume Interaction has a flexible field or we append to text.
            
            # Pack data into a structured format for frontend
            challenge_payload = {
                "type": "fill_in_the_blank",
                "data": fill_data
            }
            
            Interaction.objects.create(
                conversation=conversation,
                type='ai_feedback',
                text_content=guide_text,
                # We might need a 'metadata' field in Interaction model for clean architecture, 
                # but for now let's append a hidden JSON block
                # Or relying on the fact that for current session, we return it in API response.
                # For history persistence, we might lose the interactive widget if we don't save it.
                # Hack: Append <CHALLENGE>JSON</CHALLENGE> to text_content
            )
            
            # Update the text content with hidden data
            full_content = guide_text + f"\n<CHALLENGE>{json.dumps(challenge_payload)}</CHALLENGE>"
            conversation.interactions.last().text_content = full_content
            conversation.interactions.last().save()

            return JsonResponse({
                'status': 'success', 
                'answer': guide_text,
                'challenge': challenge_payload
            })

        elif intent == 'finish':
            # AI determined that the logical chain is complete
            conversation.status = 'review'
            conversation.save()
            
            guide_text = "你已经完成了整个视觉探索旅程。现在，请试着用一句话总结：为什么会有石油？（这是最后一步，请给出你的定义）"
            
            Interaction.objects.create(
                conversation=conversation,
                type='ai_feedback',
                text_content=guide_text
            )
            return JsonResponse({'status': 'success', 'answer': guide_text})

        elif intent == 'explaining_image':
            is_pass = analysis.get('evaluation') == 'pass'
            
            if is_pass:
                # Mark the current user interaction as passed
                current_user_interaction = conversation.interactions.last()
                if current_user_interaction:
                    current_user_interaction.is_passed = True
                    current_user_interaction.save()

                # Generate next step image
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

    # 4. Review 状态 (Final Synthesis)
    elif conversation.status == 'review':
         # User just submitted their synthesis
         # AI needs to evaluate it and give final closure
         
         # Save user's synthesis
         Interaction.objects.create(
            conversation=conversation, 
            type='user_synthesis', 
            text_content=user_input
         )
         
         final_review = {
            "summary": "你通过观察与推理，最终得出了结论。",
            "thinking_path": [{"stage": "Done", "description": "User synthesized the answer."}],
            "advice": f"你的总结：'{user_input}' 抓住了核心。保持这种观察力。"
         }
         
         conversation.is_completed = True
         conversation.save()
         
         ThinkingReview.objects.create(
            conversation=conversation,
            summary_text=final_review['summary'],
            thinking_path_json=final_review['thinking_path'],
            advice_text=final_review['advice']
         )
         
         return JsonResponse({'status': 'success', 'answer': f"<FINAL_REVIEW>{json.dumps(final_review)}</FINAL_REVIEW>"})
         
    else:
        Interaction.objects.create(conversation=conversation, type='ai_feedback', text_content="我不太理解。请试着描述图片与问题的关系。")
        return JsonResponse({'status': 'success', 'answer': "我不太理解..."})

def _handle_relativity_demo(conversation, user_input, is_start, uploaded_image_url):
    """
    Hardcoded script for "General Relativity for Babies" style demo.
    Refined for maximum "Anti-AI Addiction" philosophy: Socratic, Visual, Insight-driven.
    """
    
    step = conversation.interactions.filter(type__in=['ai_feedback', 'ai_image']).count()
    ai_service = DeepSeekService()
    
    # Initialize Demo
    if is_start:
        conversation.topic = "[DEMO] Relativity"
        conversation.status = 'visual_loop' 
        conversation.save()
        
        # Save user question
        Interaction.objects.create(conversation=conversation, type='question', text_content=user_input)
        
        # Step 0: The Hook
        answer = "我们忘掉那些复杂的公式。想象我们要从零开始构建一个宇宙。准备好了吗？"
        Interaction.objects.create(conversation=conversation, type='ai_feedback', text_content=answer)
        return JsonResponse({'status': 'success', 'answer': answer})

    # Save user input for current step
    Interaction.objects.create(conversation=conversation, type='user_interpretation', text_content=user_input, image_url=uploaded_image_url)

    # Script Steps
    
    if step == 1: 
        # Step 1: The Void (Inertia)
        prompt = "Minimalist abstract art. An infinite, perfectly flat white grid lines on light gray background. 2D plane. Nothing else. Clean, scientific style."
        text = "第一步：这是宇宙的初始状态，一片绝对平坦、空无一物的空间。\n\n**提问**：如果在这个绝对平坦的表面上，你向前方滚出一颗弹珠，它会怎么运动？会停下来，还是永远走直线？"
        
        image_url = ai_service.generate_image(prompt)
        
        Interaction.objects.create(
            conversation=conversation, type='ai_image', 
            image_url=image_url, image_prompt=prompt, text_content=text
        )
        return JsonResponse({'status': 'success', 'answer': text, 'image_url': image_url})

    elif step == 2: 
        # Step 2: The Mass (Curvature)
        prompt = "Minimalist 3D render. A heavy, dark matte sphere sitting in the center of a white grid. The grid lines bend and sink deeply underneath the sphere's weight, creating a funnel shape or gravity well. High contrast."
        text = "现在，我们在中心放入一个极重的星球（比如太阳）。\n\n**观察**：请仔细看它周围的网格。发生了什么变化？那个原本平坦的舞台现在变得怎么样了？"
        
        image_url = ai_service.generate_image(prompt)
        
        Interaction.objects.create(
            conversation=conversation, type='ai_image', 
            image_url=image_url, image_prompt=prompt, text_content=text
        )
        return JsonResponse({'status': 'success', 'answer': text, 'image_url': image_url})

    elif step == 3: 
        # Step 3: The Interaction (Gravity as Geometry)
        prompt = "Minimalist physics diagram. Top-down view. A large central mass distorting the grid. A small marble is rolling past it. The path of the marble curves towards the center, following the bent grid lines. Dashed line showing the path."
        text = "关键时刻来了。现在有一颗小行星飞过。它本想继续走直线，但地面已经塌陷了。\n\n**思考**：它的路径看起来会是怎样的？看起来像是被太阳‘吸’过去了吗？还是它只是在顺着弯路走？"
        
        image_url = ai_service.generate_image(prompt)
        
        Interaction.objects.create(
            conversation=conversation, type='ai_image', 
            image_url=image_url, image_prompt=prompt, text_content=text
        )
        return JsonResponse({'status': 'success', 'answer': text, 'image_url': image_url})

    elif step == 4: 
        # Step 4: The Epiphany (Conclusion Challenge)
        guide_text = "没错。这就是爱因斯坦的洞见：根本没有看不见的‘拉力’。小行星只是在弯曲的空间里试图走直线而已。"
        
        challenge_payload = {
            "type": "fill_in_the_blank",
            "data": {
                "question": "引力的本质不是力，而是 ___ 的弯曲。",
                "correct_answer": "时空",
                "hint": "时间和空间..."
            }
        }
        
        # Save challenge
        full_content = guide_text + f"\n<CHALLENGE>{json.dumps(challenge_payload)}</CHALLENGE>"
        
        Interaction.objects.create(
            conversation=conversation, type='ai_feedback', text_content=full_content
        )
        
        return JsonResponse({
            'status': 'success', 
            'answer': guide_text,
            'challenge': challenge_payload
        })
        
    else:
        # Finish
        guide_text = "你已经掌握了广义相对论的核心：**物质告诉时空如何弯曲，时空告诉物质如何运动**。\n\n这就是为什么我们不再需要‘引力’这个概念，我们只需要几何学。"
        
        # Mark completed
        final_review = {
            "summary": "通过构建空间模型，你领悟了引力即几何。",
            "thinking_path": [{"stage": "Done", "description": "Relativity Demo Completed"}],
            "advice": "下次看到苹果落地，试着想象一下空间本身的滑梯。"
        }
        conversation.is_completed = True
        conversation.save()
        
        Interaction.objects.create(
            conversation=conversation, type='ai_feedback', text_content=guide_text
        )
        
        return JsonResponse({'status': 'success', 'answer': f"{guide_text}<FINAL_REVIEW>{json.dumps(final_review)}</FINAL_REVIEW>"})