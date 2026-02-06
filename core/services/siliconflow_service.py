import json
import requests
from django.conf import settings
from openai import OpenAI

class SiliconFlowService:
    def __init__(self):
        self.api_key = getattr(settings, 'SILICONFLOW_API_KEY', '')
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.siliconflow.cn/v1"
        )
        # 模型配置
        self.llm_model = "Qwen/Qwen2.5-72B-Instruct"  # 或 deepseek-ai/DeepSeek-V3
        self.image_model = "black-forest-labs/FLUX.1-schnell"

    def chat_completion(self, messages, json_mode=False):
        """
        调用 LLM 进行对话或逻辑判断
        """
        try:
            response = self.client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                response_format={"type": "json_object"} if json_mode else None,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"SiliconFlow LLM Error: {e}")
            return None

    def generate_image(self, prompt):
        """
        调用 FLUX.1 生成图片
        """
        try:
            response = self.client.images.generate(
                model=self.image_model,
                prompt=prompt,
                size="1024x1024",
                n=1
            )
            # SiliconFlow 返回的是 url
            return response.data[0].url
        except Exception as e:
            print(f"SiliconFlow Image Gen Error: {e}")
            return None

    def analyze_user_input(self, question, user_input, context_history):
        """
        分析用户输入的意图和逻辑
        """
        system_prompt = """
        你是一个思维导师。你需要分析用户的输入。
        根据当前的问题和历史，判断用户的输入是：
        1. 提供了具体的想法 (has_idea)
        2. 表示不知道/没有想法 (no_idea)
        3. 正在尝试解释图片 (explaining_image)
        
        如果是在解释图片，请评估其解释是否合理（pass/fail），并给出 feedback。
        
        请以 JSON 格式返回：
        {
            "intent": "has_idea" | "no_idea" | "explaining_image",
            "evaluation": "pass" | "fail" (仅在 explaining_image 时有效),
            "feedback": "简短的反馈",
            "next_step_hint": "如果失败，给出的提示"
        }
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context: {context_history}\nQuestion: {question}\nUser Input: {user_input}"}
        ]
        
        result = self.chat_completion(messages, json_mode=True)
        try:
            return json.loads(result)
        except:
            return {"intent": "unknown", "feedback": "解析失败"}

    def generate_visual_prompt(self, question, current_stage_thought):
        """
        基于当前思维阶段，生成用于画图的 Prompt
        """
        system_prompt = """
        你是一个视觉思维专家。你需要将一个抽象的逻辑点转化为一个具体的、极具隐喻性的视觉场景。
        生成的 Prompt 必须是英文。
        不要包含文字解释，只描述画面。
        画面风格应该是：超现实主义、极简主义、充满隐喻。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\nCurrent Thought: {current_stage_thought}\nGenerate a visual prompt for this thought."}
        ]
        return self.chat_completion(messages)
