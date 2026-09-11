from dataclasses import dataclass

from langgraph.graph.state import CompiledStateGraph
from shikigen.run_manager import RunManager
from shikigen.stream import StreamManager

from app.persistence import ChatStore


@dataclass(slots=True)
class ServerRuntime:
  """应用生命周期内由所有 HTTP 请求共享的 Agent 运行时。"""

  agent: CompiledStateGraph
  stream_manager: StreamManager
  run_manager: RunManager
  chat_store: ChatStore

  async def shutdown(self) -> None:
    """停止并回收服务器仍持有的所有 run。"""
    await self.run_manager.shutdown()
