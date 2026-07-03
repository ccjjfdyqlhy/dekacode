from skill import Skill
from models import SkillResult


class SymbolSearchSkill(Skill):
    def __init__(self, graph):
        self._graph = graph

    @property
    def name(self) -> str:
        return "symbol_search"

    @property
    def description(self) -> str:
        return "Search for symbols (classes, functions) by name across the project"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Symbol name or partial name to search for",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, **kwargs) -> SkillResult:
        results = self._graph.search(query)
        if not results:
            return SkillResult(success=True, output=f"No symbols matching '{query}'")
        lines = [f"({len(results)} matches)"]
        for s in results:
            lines.append(s.to_compact())
        return SkillResult(success=True, output="\n".join(lines))


class CallersSkill(Skill):
    def __init__(self, graph):
        self._graph = graph

    @property
    def name(self) -> str:
        return "callers"

    @property
    def description(self) -> str:
        return "Find all functions that call a given symbol"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Exact symbol name (e.g. 'handle_request' or 'ClassName.method_name')",
                },
                "depth": {
                    "type": "integer",
                    "description": "How many levels up the call chain to traverse (default: 2)",
                },
            },
            "required": ["symbol"],
        }

    async def execute(self, symbol: str, depth: int = 2, **kwargs) -> SkillResult:
        from code_graph.search import get_call_chain_text
        text = get_call_chain_text(self._graph, symbol, depth)
        return SkillResult(success=True, output=text)


class ReadSymbolSkill(Skill):
    def __init__(self, graph):
        self._graph = graph

    @property
    def name(self) -> str:
        return "read_symbol"

    @property
    def description(self) -> str:
        return "Read the source code of a specific symbol (class/function) by name, without reading the entire file"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Exact symbol name (e.g. 'ContextManager' or 'ContextManager.build_request')",
                },
            },
            "required": ["symbol"],
        }

    async def execute(self, symbol: str, **kwargs) -> SkillResult:
        from code_graph.search import get_symbol_source
        source = get_symbol_source(self._graph, symbol)
        if source is None:
            return SkillResult(success=False, output=f"Symbol '{symbol}' not found")
        if len(source) > 10000:
            source = source[:10000] + f"\n[...truncated, total {len(source)} chars]"
        return SkillResult(success=True, output=source)
