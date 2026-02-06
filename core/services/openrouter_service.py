import json
import requests
from django.conf import settings
from openai import OpenAI

class OpenRouterService:
    def __init__(self):
        self.api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
        # OpenRouter 兼容 OpenAI SDK
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )
        # 模型配置
        # 使用 Google Gemini 2.0 Flash (目前在 OpenRouter 上免费/极低成本)
        self.llm_model = "google/gemini-2.0-flash-001" 
        # 生图模型：Flux 1 Schnell
        self.image_model = "black-forest-labs/flux-1-schnell"

    def chat_completion(self, messages, json_mode=False):
        """
        调用 LLM 进行对话或逻辑判断
        """
        print(f"DEBUG: Calling OpenRouter LLM with model {self.llm_model}...")
        extra_headers = {
            "HTTP-Referer": "https://thinkfirst.app", # OpenRouter 要求
            "X-Title": "ThinkFirst"
        }
        
        try:
            response = self.client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                response_format={"type": "json_object"} if json_mode else None,
                temperature=0.7,
                extra_headers=extra_headers
            )
            content = response.choices[0].message.content
            print(f"DEBUG: LLM Response: {content[:100]}...")
            return content
        except Exception as e:
            print(f"ERROR: OpenRouter LLM Error: {e}")
            return None

    def generate_image(self, prompt):
        """
        调用 Pollinations.ai 生成图片 (免费、无需Key、稳定)
        """
        import urllib.parse
        print(f"DEBUG: Generating image with prompt: {prompt[:50]}...")
        try:
            # Pollinations.ai API: https://image.pollinations.ai/prompt/{prompt}
            # 需要对 prompt 进行 URL 编码
            encoded_prompt = urllib.parse.quote(prompt)
            # 添加一些参数以增强效果，例如 seed (虽然 pollinations 默认随机)
            # nologo=true 去除水印
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?nologo=true&width=1024&height=1024&model=flux"
            
            print(f"DEBUG: Image generated via Pollinations: {url}")
            return url
        except Exception as e:
            print(f"ERROR: Image Gen Error: {e}")
            return "https://placehold.co/1024x1024/png?text=Image+Error"

    def analyze_user_input(self, question, user_input, context_history):
        """
        分析用户输入的意图和逻辑
        """
        system_prompt = """
        You are a Socratic Tutor. Analyze the user's input based on the question and context.
        
        Determine if the user:
        1. "has_idea": Provided a specific thought/idea about the question.
        2. "no_idea": Said they don't know or have no idea.
        3. "explaining_image": Is interpreting the AI-generated image shown to them.
        
        If "explaining_image", evaluate if their interpretation makes logical sense or connects to the core problem (pass/fail).
        
        Return JSON:
        {
            "intent": "has_idea" | "no_idea" | "explaining_image",
            "evaluation": "pass" | "fail" (only if explaining_image),
            "feedback": "Short feedback in Chinese",
            "next_step_hint": "Hint if failed, in Chinese"
        }
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context History:\n{context_history}\n\nCurrent Question: {question}\nUser Input: {user_input}"}
        ]
        
        result = self.chat_completion(messages, json_mode=True)
        try:
            # 有些模型可能返回 markdown code block，需要清洗
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
