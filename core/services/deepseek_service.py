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
        
        **CRITICAL STEP: Determine Cognitive Level & Visual Tool**
        1. **Curiosity/Nature/Life** (e.g., "Why is sky blue?", "How do trees grow?", "History of Rome"):
           - Tool: **IMAGE_GENERATION** (Flux.1)
           - Style: **REALISTIC, CINEMATIC, DOCUMENTARY PHOTOGRAPHY**.
        2. **Math/Functions/Geometry** (e.g., "y=x^2", "Sin wave", "Parabola properties"):
           - Tool: **DESMOS_CALCULATOR**
           - Action: Generate a specific LaTeX formula for Desmos.
        3. **Academic/Abstract/Logic** (non-math):
           - Tool: **IMAGE_GENERATION**
           - Style: **MINIMALIST, INFOGRAPHIC**.

        RETURN JSON FORMAT:
        {
            "intent": "has_idea" | "no_idea" | "explaining_image",
            "tool": "image_generation" | "desmos",
            "desmos_latex": "y=x^2" (only if tool is desmos),
            "evaluation": "pass" | "fail",
            "feedback": "Short feedback in Chinese.",
            "next_step_hint": "Hint if failed.",
            "visual_prompt": "English prompt for Flux.1 (if tool is image_generation)",
            "visual_guide_text": "Chinese guide text."
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
        
        **Determine the Subject Matter & Style:**
        - **Nature/Real Life:** Use "Cinematic, Photorealistic, National Geographic Style".
        - **Academic/Abstract/Logic/Math:** Use "Minimalist, Schematic, Blueprint, Infographic, Vector Art, Clean Lines, High Concept".
        
        OUTPUT ONLY THE VISUAL DESCRIPTION PROMPT IN ENGLISH. NO OTHER TEXT.
        Style should be consistent with the subject matter.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\nCurrent Thought to Visualize: {current_stage_thought}"}
        ]
        return self.chat_completion(messages)

    def analyze_image_content(self, image_path, prompt):
        """
        调用 SiliconFlow Vision 模型 (Qwen2-VL) 分析图片
        """
        import base64
        import requests
        
        print(f"DEBUG: Analyzing image {image_path} via SiliconFlow...")
        
        silicon_key = getattr(settings, 'SILICONFLOW_API_KEY', '')
        if not silicon_key:
            return "Error: SiliconFlow API Key not set."

        # Encode image
        try:
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                # Assume jpeg/png, base64 header usually works generically or we can detect type
                # But Qwen/OpenAI usually accepts data:image/jpeg;base64 even for png
                image_url = f"data:image/jpeg;base64,{encoded_string}"
        except Exception as e:
            return f"Error reading image: {e}"

        try:
            url = "https://api.siliconflow.cn/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {silicon_key}",
                "Content-Type": "application/json"
            }
            
            # Using Qwen2-VL-72B-Instruct (Better) or 7B. Let's try 72B for quality if available, or 7B.
            # Safe bet: Qwen/Qwen2-VL-7B-Instruct
            model_name = "Qwen/Qwen2-VL-72B-Instruct" 
            
            if not prompt:
                prompt = "请详细描述这张图片的内容，并结合上下文分析它。"

            payload = {
                "model": model_name, 
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                "max_tokens": 1024
            }
            
            response = requests.post(url, json=payload, headers=headers)
            # If 72B fails (e.g. 404 or 400), fallback to 7B? 
            # But let's assume it works or just use 7B which is safer.
            # Actually, let's use 7B to be safe on quota/availability.
            if response.status_code != 200:
                print(f"WARNING: Vision API failed with {model_name}, trying 7B...")
                payload["model"] = "Qwen/Qwen2-VL-7B-Instruct"
                response = requests.post(url, json=payload, headers=headers)

            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
            
        except Exception as e:
            print(f"ERROR: SiliconFlow Vision Error: {e}")
            if 'response' in locals():
                print(f"Response: {response.text}")
            return f"图片分析失败: {str(e)}"

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
