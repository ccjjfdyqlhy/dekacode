import httpx

from models import SkillResult
from skill import Skill


class WebFetchSkill(Skill):
    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch URL content"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
        },
        "required": ["url"],
    }

    async def execute(self, url: str, **kwargs) -> SkillResult:
        try:
            headers = {"User-Agent": "Dekacode/1.0"}
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                text = resp.text
                total = len(text)
                if total > 20000:
                    text = text[:20000] + f"\n\n[...{total} chars total, truncated to 20000]"
                return SkillResult(success=True, output=text)
        except Exception as e:
            return SkillResult(success=False, output=str(e))
