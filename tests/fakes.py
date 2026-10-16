"""A scripted stand-in for the anthropic client used by the live-path tests."""
from src.claude_client import TOOL_NAME


class Block:
    def __init__(self, inp):
        self.type, self.name, self.id, self.input = "tool_use", TOOL_NAME, "toolu_1", inp


class Usage:
    input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 1200, 800, 1100, 0


class Resp:
    def __init__(self, inp, stop="tool_use"):
        self.content, self.usage, self.model, self.stop_reason = [Block(inp)], Usage(), "claude-sonnet-5-5", stop


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)
