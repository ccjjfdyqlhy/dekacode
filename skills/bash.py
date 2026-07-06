import asyncio

from models import SkillResult
from skill import Skill


class BashSkill(Skill):
    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Run bash command"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "workdir": {"type": "string"},
        },
        "required": ["command"],
    }

    async def execute(self, command: str, workdir: str | None = None, **kwargs) -> SkillResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                decoded_stderr = stderr.decode("utf-8", errors="replace")
                if decoded_stderr.strip():
                    output += f"\n[stderr]\n{decoded_stderr}"
            total = len(output)
            if total > 20000:
                output = output[:20000] + f"\n\n[...{total} chars total, truncated to 20000]"
            return SkillResult(success=proc.returncode == 0, output=output)
        except asyncio.TimeoutError:
            return SkillResult(success=False, output="Command timed out after 60s")
        except Exception as e:
            return SkillResult(success=False, output=str(e))
