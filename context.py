import re
import os

from models import Message

_UNDEFINED_SYMBOL_RE = re.compile(r"NameError: name '(\w+)' is not defined|'(\w+)' object has no attribute|undefined symbol: (\w+)|Unresolved reference: (\w+)")


class SpeculativePrefetcher:
    def __init__(self, graph):
        self.graph = graph

    def analyze(self, text: str) -> list[str]:
        names = set()
        for m in _UNDEFINED_SYMBOL_RE.finditer(text):
            for g in m.groups():
                if g:
                    names.add(g)
        results = []
        for name in names:
            sym = self.graph.get(name)
            if not sym:
                for sname, s in self.graph.symbols.items():
                    if name in sname or name.lower() == sname.split(".")[-1].lower():
                        results.append(sname)
                        break
        return results

    def prefetch(self, symbol_names: list[str]) -> str:
        blocks = []
        seen = set()
        for name in symbol_names:
            if name in seen:
                continue
            seen.add(name)
            sym = self.graph.get(name)
            if not sym:
                continue
            fpath = sym.file_path
            if not os.path.isabs(fpath):
                candidates = [f for f in self.graph.files if f.endswith(fpath)]
                fpath = candidates[0] if candidates else fpath
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except (FileNotFoundError, IOError):
                    continue
            else:
                continue
            start = max(0, sym.line - 1)
            end = min(len(lines), start + 15)
            source = "".join(lines[start:end])
            blocks.append(f"# {sym.signature}  ({sym.file_path}:{sym.line})\n{source}")
        return "\n\n".join(blocks) if blocks else ""


class ContextManager:
    def __init__(self, system_prompt: str):
        self.prefix: list[Message] = [Message(role="system", content=system_prompt)]
        self.history: list[Message] = []
        self.draft: list[Message] = []

    def build_request(self) -> list[Message]:
        return self.prefix + self.history + self.draft

    def commit_draft(self) -> None:
        self.history.extend(self.draft)
        self.draft.clear()

    def rollback_draft(self) -> None:
        self.draft.clear()

    def add_user_message(self, content: str) -> None:
        self.history.append(Message(role="user", content=content))

    def add_assistant_message(self, msg: Message) -> None:
        self.history.append(msg)

    def add_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.draft.append(
            Message(role="tool", tool_call_id=tool_call_id, name=name, content=content)
        )

    def total_messages(self) -> int:
        return len(self.prefix) + len(self.history) + len(self.draft)

    def set_prefix_attachment(self, content: str) -> None:
        attachment = Message(role="system", content=content)
        existing = [m for m in self.prefix if m.content == attachment.content]
        if not existing:
            self.prefix.append(attachment)

    def clear_prefix_attachments(self) -> None:
        self.prefix = [self.prefix[0]]
