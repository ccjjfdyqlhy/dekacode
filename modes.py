from enum import Enum


class AgentMode(str, Enum):
    AGENT = "agent"
    ONESHOT = "oneshot"


class ModeState:
    def __init__(self, mode: AgentMode = AgentMode.AGENT):
        self.mode = mode

    def toggle(self) -> AgentMode:
        if self.mode == AgentMode.AGENT:
            self.mode = AgentMode.ONESHOT
        else:
            self.mode = AgentMode.AGENT
        return self.mode

    def set(self, mode: str) -> None:
        self.mode = AgentMode(mode)

    def is_oneshot(self) -> bool:
        return self.mode == AgentMode.ONESHOT

    def is_agent(self) -> bool:
        return self.mode == AgentMode.AGENT
