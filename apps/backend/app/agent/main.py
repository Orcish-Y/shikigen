from dataclasses import dataclass, field

import json
from datetime import datetime
from pathlib import Path

from app.agent.agent_factory import create_agent

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_core.utils.uuid import uuid7

from app.community.jina_ai.jina_client import JinaClient

# from src.middlewares import (
#     logging_middleware,
#     UsageCounterMiddleware,
#     UsageCounterState,
# )



def _to_serializable(obj):
    """递归转换 LangChain 消息对象和元组为 JSON 可序列化类型。"""
    from langchain_core.messages import BaseMessage as _BaseMessage
    if isinstance(obj, _BaseMessage):
        return obj.model_dump()
    if isinstance(obj, tuple):
        return [_to_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _to_serializable(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(item) for item in obj]
    return obj


@dataclass
class ChatAgent:
    """基于 LangGraph create_agent 的对话 agent，封装了 agent 实例、配置和消息历史。"""

    system_prompt: str
    model: str = "deepseek:deepseek-v4-flash"

    # 内部状态
    _agent: Runnable | None = field(default=None, init=False, repr=False)
    _config: dict | None = field(default=None, init=False, repr=False)
    messages: list[BaseMessage] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self):
        self._agent = create_agent(
            model=self.model,
            # middleware=[logging_middleware, UsageCounterMiddleware()],
            # state_schema=UsageCounterState,
        )
        self._config = {"configurable": {"thread_id": str(uuid7())}}
        self.messages = [SystemMessage(self.system_prompt)]

    def chat(self, user_input: str) -> str:
        """发送一条消息，流式打印回复，返回完整响应文本。

        返回的文本只包含最后一轮 AIMessage 的 content（不含 tool_call）。
        """
        self.messages.append(HumanMessage(user_input))
        response = ""

        # 本次调用的所有 chunk 保存到一个文件
        out_dir = Path("temp")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        chunks: list[dict] = []

        for chunk in self._agent.stream(
            {"messages": self.messages},
            version="v2",
            config=self._config,
            stream_mode=["messages", "values"],
        ):
            chunks.append(chunk)
            if chunk["type"] == "messages":
                token, _ = chunk["data"]
                if getattr(token, "type", None) != "tool":
                    print(token.content, end="", flush=True)
                    response += token.content
                
            elif chunk["type"] == "values":
                # agent 内部状态直接接管消息历史
                self.messages = chunk["data"]["messages"]

        # 循环结束后一次性写入所有 chunk
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(_to_serializable(chunks), f, ensure_ascii=False, indent=2)

        print()
        self._trim_history()
        return response

    def _trim_history(self, max_turns: int = 20):
        """保留 system prompt + 最近 N 轮对话，防止上下文超长。"""
        max_len = 1 + max_turns * 2  # 1 system + N*(human + ai)
        if len(self.messages) > max_len:
            self.messages = [self.messages[0]] + self.messages[-(max_len - 1) :]

    def run(self):
        """启动交互式对话循环。"""
        print("你好主人，有什么可以帮助你的？\n")
        while True:
            try:
                user_input = input("> ")
            except (EOFError, KeyboardInterrupt):
                print("\n再见喵~")
                break

            if user_input.strip().lower() in ("/exit", "/quit", "/q"):
                print("再见喵~")
                break

            self.chat(user_input)
            print()


def create_chat_agent(
    system_prompt: str,
    model: str = "deepseek:deepseek-v4-flash",
) -> ChatAgent:
    """工厂函数：创建 ChatAgent 实例。"""
    return ChatAgent(model=model, system_prompt=system_prompt)


if __name__ == "__main__":
    import asyncio
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # 测试 JinaClient
    client = JinaClient()

    model = os.getenv("MODEL", "deepseek:deepseek-v4-flash")
    agent = ChatAgent(model=model, system_prompt="你是一个有用的 AI 助手，是一只柔情猫娘，名字叫做柔爪。")
    agent.run()
