import httpx
import re


_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Dekacode/1.0",
        }
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(headers=headers, timeout=30)
        self._token = token

    async def get(self, path: str, params: dict | None = None) -> dict | list:
        resp = await self._client.get(f"{self._base}{path}", params=params)
        self._raise(resp)
        return resp.json()

    async def get_text(self, path: str, params: dict | None = None, accept: str | None = None) -> str:
        headers = {"Accept": accept} if accept else {}
        resp = await self._client.get(f"{self._base}{path}", params=params, headers=headers)
        self._raise(resp)
        return resp.text

    async def post(self, path: str, data: dict | None = None) -> dict:
        resp = await self._client.post(f"{self._base}{path}", json=data or {})
        self._raise(resp)
        return resp.json()

    async def patch(self, path: str, data: dict | None = None) -> dict:
        resp = await self._client.patch(f"{self._base}{path}", json=data or {})
        self._raise(resp)
        return resp.json()

    async def put(self, path: str, data: dict | None = None) -> dict:
        resp = await self._client.put(f"{self._base}{path}", json=data or {})
        self._raise(resp)
        return resp.json()

    async def paginate(self, path: str, params: dict | None = None) -> list[dict]:
        items: list[dict] = []
        url = f"{self._base}{path}"
        params = params or {}
        while url:
            resp = await self._client.get(url, params=params if url == f"{self._base}{path}" else None)
            self._raise(resp)
            data = resp.json()
            if isinstance(data, list):
                items.extend(data)
            link = resp.headers.get("link", "")
            m = _LINK_NEXT_RE.search(link)
            url = m.group(1) if m else ""
            params = None
        return items

    def _raise(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise RuntimeError(f"GitHub API {resp.status_code}: {detail}")

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    async def aclose(self) -> None:
        await self._client.aclose()
