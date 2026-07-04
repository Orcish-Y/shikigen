
from app.agent.tools.registry import ToolRegistry
from app.community.jina_ai.tool import web_fetch_tool
from langchain_core.tools import BaseTool

def get_available_tools() -> list[BaseTool]:
    """Get all available tools from the registry."""
    registry = ToolRegistry()

    registry.register(web_fetch_tool)


    return registry.get_tools()