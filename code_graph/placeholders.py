import os
import re

from code_graph.symbol import CallGraph

_FETCH_RE = re.compile(r"\[FETCH:(Class|Function|Method|Variable|Symbol):(\w+(?:\.\w+)*)\]")


class PlaceholderResolver:
    def __init__(self, graph: CallGraph):
        self.graph = graph

    def resolve(self, text: str) -> tuple[str, list[dict]]:
        cleaned = _FETCH_RE.sub("", text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        symbols_to_fetch = []
        for m in _FETCH_RE.finditer(text):
            kind = m.group(1)
            name = m.group(2)
            symbols_to_fetch.append({"kind": kind, "name": name})

        return cleaned, symbols_to_fetch

    def fetch(self, symbols_to_fetch: list[dict]) -> str:
        blocks = []
        seen = set()

        for item in symbols_to_fetch:
            name = item["name"]
            if name in seen:
                continue
            seen.add(name)

            sym = self.graph.get(name)
            if not sym:
                for sname, s in self.graph.symbols.items():
                    if sname.endswith(f".{name}") or sname == name:
                        sym = s
                        break

            if not sym:
                blocks.append(f"# [FETCH:{item['kind']}:{name}] — not found in project")
                continue

            fpath = sym.file_path
            if not os.path.isabs(fpath):
                candidates = [f for f in self.graph.files if f.endswith(fpath)]
                fpath = candidates[0] if candidates else fpath

            if not os.path.isfile(fpath):
                blocks.append(f"# [FETCH:{item['kind']}:{name}] — file not found: {fpath}")
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except (FileNotFoundError, IOError):
                blocks.append(f"# [FETCH:{item['kind']}:{name}] — cannot read file")
                continue

            start = max(0, sym.line - 1)
            if item["kind"] in ("Class",):
                base_indent = len(lines[start]) - len(lines[start].lstrip())
                end = start + 1
                for i in range(start + 1, min(len(lines), start + 80)):
                    if i >= len(lines):
                        break
                    stripped = lines[i].rstrip()
                    if not stripped or stripped.startswith("#"):
                        end = i + 1
                        continue
                    indent = len(lines[i]) - len(lines[i].lstrip())
                    if indent <= base_indent and not stripped.startswith((" ", "\t")):
                        break
                    end = i + 1
            else:
                end = min(len(lines), start + 20)

            source = "".join(lines[start:end])
            blocks.append(
                f"# {item['kind']}: {name}  ({sym.file_path}:{sym.line})\n{source}"
            )

        return "\n\n".join(blocks) if blocks else ""

    @staticmethod
    def has_placeholders(text: str) -> bool:
        return bool(_FETCH_RE.search(text))
