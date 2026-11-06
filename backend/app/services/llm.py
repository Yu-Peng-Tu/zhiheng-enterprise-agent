import json
import httpx
from ..core.config import settings

class LLMClient:
    def __init__(self):
        self.enabled = bool(settings.llm_api_key)

    def grounded_answer(self, question: str, citations: list[dict]):
        if not citations or citations[0]["score"] < 0.16 or citations[0]["lexical_score"] == 0:
            citations.clear()
            return "当前知识库依据不足，无法可靠回答。请补充相关企业文档或换一种问法。", "offline", {"prompt_tokens": 0, "completion_tokens": 0}
        if not self.enabled:
            primary = citations[0]["content"].strip()
            answer = f"{primary}\n\n以上回答依据《{citations[0]['document_name']}》{citations[0]['locator']}，可点击右侧引用核验。"
            return answer, "offline-grounded", {"prompt_tokens": 0, "completion_tokens": 0}
        evidence = "\n\n".join(f"[{i+1}] {item['document_name']} {item['locator']}\n{item['content']}" for i, item in enumerate(citations))
        prompt = f"仅依据证据回答用户问题，不得补充证据外事实。答案末尾用[1]形式标注引用。\n\n证据：\n{evidence}\n\n问题：{question}"
        try:
            with httpx.Client(timeout=45) as client:
                response = client.post(
                    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json={"model": settings.llm_model, "messages": [{"role":"user","content":prompt}], "temperature":0.1},
                )
                response.raise_for_status()
                payload = response.json()
                return payload["choices"][0]["message"]["content"], settings.llm_model, payload.get("usage", {})
        except Exception:
            primary = citations[0]["content"].strip()
            return f"{primary}\n\n（在线模型暂不可用，已切换为本地依据摘录。）", "offline-fallback", {"prompt_tokens": 0, "completion_tokens": 0}

llm_client = LLMClient()
