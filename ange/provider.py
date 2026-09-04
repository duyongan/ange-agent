"""Provider 适配层:仅 OpenAI 兼容端点(DeepSeek 默认)。

一万行预算里只此一条适配路;不学 hermes 做 39 家 profile。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import Settings


def build_chat_model(settings: Settings, *, review: bool = False, temperature: float = 0.3) -> ChatOpenAI:
    """主模型与复盘模型共用同一适配;review=True 时可走便宜档。"""
    model = settings.effective_review_model if review else settings.model
    return ChatOpenAI(
        model=model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=temperature,
        max_retries=2,
    )
