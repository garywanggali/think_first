import requests
import json
import time
import random
from django.conf import settings

class DifyService:
    def __init__(self):
        self.api_key = getattr(settings, 'DIFY_API_KEY', '')
        self.base_url = getattr(settings, 'DIFY_API_URL', 'https://api.dify.ai/v1')
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    def send_message(self, query, user_id, conversation_id=None, inputs=None):
        """
        发送消息到 Dify。如果未配置 API Key，则使用 Mock 数据。
        """
        if self.api_key == 'Please_Set_Your_Dify_Key_Here' or not self.api_key:
            return self._mock_response(query, conversation_id)

        url = f"{self.base_url}/chat-messages"
        
        payload = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": "blocking",
            "conversation_id": conversation_id if conversation_id else "",
            "user": str(user_id)
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error communicating with Dify: {e}")
            # Fallback to mock if API fails (for demo purposes)
            return self._mock_response(query, conversation_id)

    def _mock_response(self, query, conversation_id):
        """
        模拟 Dify 的苏格拉底式回复
        """
        time.sleep(1) # Simulate network delay
        
        # 简单的状态机模拟
        # 如果包含 "图" -> 认为用户展示了思考
        # 如果包含 "因为" -> 认为用户在解释
        # 如果包含 "结束" -> 生成报告
        
        answer = ""
        
        if not conversation_id:
            answer = "收到你的问题。但我不会直接告诉你答案。请先告诉我，关于这个问题，你最初的直觉是什么？"
        elif "图" in query or "画" in query:
            answer = "很有趣的图示。我注意到你把核心概念放在了中间，但似乎忽略了外部的影响因素。你能试着添加一下环境变量的影响吗？"
        elif "因为" in query:
             answer = "你的推理很有逻辑。但是，这个‘因为’的前提是否总是成立？有没有反例？"
        elif "不知道" in query:
             answer = "没关系，卡住是思考的一部分。试着把问题拆解成三个小部分，你会怎么拆？"
        elif "结束" in query or "完成" in query:
             answer = """你的思考已经很完整了。这是对你这次思维旅程的回顾：
<FINAL_REVIEW>
{
  "summary": "用户从最初的模糊提问，通过可视化的方式梳理了变量关系，最终意识到了系统性风险的存在。",
  "thinking_path": [
    {"stage": "提出问题", "description": "用户关注单一变量"},
    {"stage": "可视化尝试", "description": "通过绘图发现了被忽略的联系"},
    {"stage": "逻辑深化", "description": "修正了因果倒置的错误"},
    {"stage": "元认知觉醒", "description": "意识到自己之前的思维盲区"}
  ],
  "advice": "你很擅长捕捉细节，但容易陷入局部最优。建议下次在深入细节前，先画一个全局的系统图。"
}
</FINAL_REVIEW>
祝你在未来的思考中继续保持这种深度。"""
        else:
            responses = [
                "这就引出了一个有趣的问题：如果这个假设不成立，后果是什么？",
                "你能举一个具体的例子来支持这个观点吗？",
                "这个看法很独特。但我们要如何验证它的真实性？",
                "试着用画图的方式表达一下这几个概念之间的关系？"
            ]
            answer = random.choice(responses)

        return {
            "event": "message",
            "task_id": "mock_task_id",
            "id": "mock_message_id",
            "answer": answer,
            "conversation_id": conversation_id or "mock_conversation_id_new",
            "created_at": int(time.time())
        }

    def file_upload(self, file_path, user_id):
        pass
