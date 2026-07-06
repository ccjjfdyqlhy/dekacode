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
        return "Search symbols by name across project"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
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
        return "Find callers of a symbol"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "depth": {"type": "integer"},
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
        return "Read symbol source by name"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
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
