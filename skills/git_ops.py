import asyncio

from models import SkillResult
from skill import Skill


class DiffFileSkill(Skill):
    @property
    def name(self) -> str:
        return "diff_file"

    @property
    def description(self) -> str:
        return "Show uncommitted git diff for a file or the whole repo"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Optional file path to show diff for (omit for full repo diff)",
                },
                "staged": {
                    "type": "boolean",
                    "description": "Show staged changes (default: show unstaged)",
                },
            },
        }

    async def execute(self, file_path: str | None = None, staged: bool = False, **kwargs) -> SkillResult:
        try:
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--cached")
            if file_path:
                cmd.append(file_path)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace")
            if not output.strip():
                return SkillResult(success=True, output="No changes (clean working tree)")
            total = len(output)
            if total > 20000:
                output = output[:20000] + f"\n\n[...{total} chars total, truncated to 20000]"
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e))
