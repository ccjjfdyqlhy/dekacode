import re


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_TIMESTAMP_RE = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_REPEATED_BLANK_RE = re.compile(r"\n{3,}")


class OutputFilter:
    @staticmethod
    def bash(output: str) -> str:
        output = _ANSI_RE.sub("", output)
        output = _TIMESTAMP_RE.sub("<ts>", output)
        output = _UUID_RE.sub("<uuid>", output)
        output = _REPEATED_BLANK_RE.sub("\n\n", output)
        return output

    @staticmethod
    def grep(output: str) -> str:
        lines = output.split("\n")
        if len(lines) > 200:
            lines = lines[:200] + [f"[...{len(lines) - 200} more lines suppressed]"]
        return "\n".join(lines)

    @staticmethod
    def web_fetch(text: str) -> str:
        text = _REPEATED_BLANK_RE.sub("\n\n", text)
        lines = text.split("\n")
        if len(lines) > 300:
            lines = lines[:300] + [f"[...{len(lines) - 300} more lines suppressed]"]
        return "\n".join(lines)
