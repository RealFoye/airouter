"""TextToolParser unit tests."""

from airouter.engine.agent.text_parser import TEXT_TOOL_SYSTEM_PROMPT, TextToolParser

TOOL_OPEN = "<tool_call>"
TOOL_CLOSE = "</tool_call>"


class TestTextToolParser:
    def test_parse_single_call(self):
        text = f"我来读取文件：\n\n{TOOL_OPEN}\nread_file\n" + chr(123) + '"path": "src/main.py"' + chr(125) + f"\n{TOOL_CLOSE}"
        parser = TextToolParser()
        calls = parser.parse(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "read_file"
        assert calls[0]["function"]["arguments"] == chr(123) + '"path": "src/main.py"' + chr(125)

    def test_parse_multiple_calls(self):
        text = (
            f"{TOOL_OPEN}\nread_file\n" + chr(123) + '"path": "a.py"' + chr(125) + f"\n{TOOL_CLOSE}\n"
            f"{TOOL_OPEN}\nedit_file\n" + chr(123) + '"path": "b.py", "old_text": "x", "new_text": "y"' + chr(125) + f"\n{TOOL_CLOSE}"
        )
        parser = TextToolParser()
        calls = parser.parse(text)
        assert len(calls) == 2
        assert calls[0]["function"]["name"] == "read_file"
        assert calls[1]["function"]["name"] == "edit_file"

    def test_parse_no_tools(self):
        text = "这段代码看起来没问题，我已经完成了修改。"
        parser = TextToolParser()
        calls = parser.parse(text)
        assert len(calls) == 0

    def test_parse_run_command(self):
        text = f"{TOOL_OPEN}\nrun_command\n" + chr(123) + '"command": "pytest tests/"' + chr(125) + f"\n{TOOL_CLOSE}"
        parser = TextToolParser()
        calls = parser.parse(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "run_command"

    def test_unique_ids(self):
        text = (
            f"{TOOL_OPEN}\nread_file\n" + chr(123) + '"path": "a.py"' + chr(125) + f"\n{TOOL_CLOSE}\n"
            f"{TOOL_OPEN}\nread_file\n" + chr(123) + '"path": "b.py"' + chr(125) + f"\n{TOOL_CLOSE}"
        )
        parser = TextToolParser()
        calls = parser.parse(text)
        ids = [c["id"] for c in calls]
        assert len(ids) == len(set(ids))

    def test_system_prompt_not_empty(self):
        assert len(TEXT_TOOL_SYSTEM_PROMPT) > 50
        assert "read_file" in TEXT_TOOL_SYSTEM_PROMPT
