import json
import urllib.parse
from django.conf import settings
from openai import OpenAI
from core.utils import save_image_from_url

class DeepSeekService:
    def __init__(self):
        self.api_key = getattr(settings, 'DEEPSEEK_API_KEY', '')
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )

    def chat_completion(self, messages, json_mode=False):
        """
        调用 DeepSeek V3
        """
        if not self.api_key or 'Please_Set' in self.api_key:
            return "Error: DeepSeek API Key not configured."
        
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=1.3,
                response_format={"type": "json_object"} if json_mode else None
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"DeepSeek API Error: {e}")
            return f"Error: {str(e)}"

    def generate_image(self, prompt):
        """
        调用 SiliconFlow 生成图片 (Flux.1 Schnell)
        """
        import requests
        print(f"DEBUG: Generating image via SiliconFlow with prompt: {prompt[:50]}...")
        
        silicon_key = getattr(settings, 'SILICONFLOW_API_KEY', '')
        if not silicon_key or 'Please_Set' in silicon_key:
            print("ERROR: SiliconFlow API Key not set.")
            return "https://placehold.co/1024x1024/png?text=API+Key+Missing"

        try:
            url = "https://api.siliconflow.cn/v1/images/generations"
            headers = {
                "Authorization": f"Bearer {silicon_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "black-forest-labs/FLUX.1-dev", # 切换到 Dev 版，质量更好
                "prompt": prompt,
                "image_size": "1024x1024",
                "num_inference_steps": 20 # Dev 版推荐 20-50 步
            }
            
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # SiliconFlow 返回格式: {"data": [{"url": "..."}]}
            original_image_url = data['data'][0]['url']
            print(f"DEBUG: Image generated via SiliconFlow: {original_image_url}")
            
            # 下载并保存到本地，防止链接过期
            local_image_url = save_image_from_url(original_image_url)
            
            if local_image_url:
                print(f"DEBUG: Image saved locally: {local_image_url}")
                return local_image_url
            else:
                print("WARNING: Failed to save image locally, returning original URL")
                return original_image_url
            
        except Exception as e:
            print(f"ERROR: SiliconFlow Image Gen Error: {e}")
            if 'response' in locals():
                print(f"Response: {response.text}")
            return "https://placehold.co/1024x1024/png?text=Image+Error"

    def analyze_user_input(self, question, user_input, context_history):
        """
        分析用户输入的意图和逻辑，并按需生成 Visual Prompt
        """
        system_prompt = """
        You are a Visual Storyteller & Science Communicator. 
        Your goal is to explain the user's question by guiding them through a **sequential visual narrative**.
        Instead of giving text answers, you generate images that depict the **process** or **evolution** of the answer, step by step.
        
        Analyze the user's input and context to determine the Next Visual Scene.
        
        Logic:
        1. If user just started (intent="has_idea" or "no_idea"): 
           - Generate the **FIRST stage/origin** of the answer. (e.g., for Oil: Ancient prehistoric forest).
        2. If user is explaining the previous image (intent="explaining_image") and evaluation is "pass":
           - Generate the **NEXT stage** of the process. (e.g., for Oil: Layers of sediment covering dead plants).
        
        RETURN JSON FORMAT:
        {
            "intent": "has_idea" | "no_idea" | "explaining_image",
            "evaluation": "pass" | "fail" (only if explaining_image),
            "feedback": "Short feedback in Chinese. Confirm what they saw and bridge to the next scene.",
            "next_step_hint": "Hint if failed, in Chinese",
            "visual_prompt": "Generate a CINEMATIC, HIGHLY DETAILED, AWARD-WINNING DOCUMENTARY PHOTOGRAPHY STYLE English prompt for the scene. Focus on the physical process. IMPORTANT: Do NOT include any text, logos, watermarks, or yellow borders.",
            "visual_guide_text": "A short, engaging Chinese guide for the user. Ask them to observe specific details in the generated scene and think about their meaning. Do NOT reveal the scientific answer directly. e.g. 'Look at the layers accumulating at the bottom... what do you think they are composed of?'"
        }
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context History:\n{context_history}\n\nCurrent Question: {question}\nUser Input: {user_input}"}
        ]
        
        result = self.chat_completion(messages, json_mode=True)
        try:
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]
            return json.loads(result)
        except Exception as e:
            print(f"JSON Parse Error: {e}, Raw: {result}")
            return {"intent": "unknown", "feedback": "解析失败"}

    def generate_visual_prompt(self, question, current_stage_thought):
        """
        生成用于画图的 Prompt
        """
        system_prompt = """
        You are a Visual Thinking Expert. Convert the abstract logic into a concrete, metaphorical visual scene.
        
        OUTPUT ONLY THE VISUAL DESCRIPTION PROMPT IN ENGLISH. NO OTHER TEXT.
        
        Style: Surrealist, Minimalist, Metaphorical. High quality, 8k resolution.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\nCurrent Thought to Visualize: {current_stage_thought}"}
        ]
        return self.chat_completion(messages)

    def generate_initial_probe(self, user_question):
        """
        生成个性化的初始引导语
        """
        system_prompt = """
        你是一个苏格拉底式的思维导师。用户刚提出了一个问题。
        你的任务是：
        1. 确认收到问题。
        2. 询问用户目前对这个问题是否有初步的直觉或想法。
        
        要求：
        - 语气温暖、专业、具有同理心。
        - 必须包含“初步想法”或“直觉”这个核心询问点。
        - 不要直接回答问题，而是引导用户开始思考。
        - 100字以内。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Question: {user_question}"}
        ]
        return self.chat_completion(messages)
