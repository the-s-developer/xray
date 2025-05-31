from enum import Enum

class AgentStatus(str, Enum):
    IDLE = "idle"
    GENERATING = "generating"
    TOOL_CALLING = "tool_calling"
    DONE = "done"
    STOPPED = "stopped",
    ERROR = "error"