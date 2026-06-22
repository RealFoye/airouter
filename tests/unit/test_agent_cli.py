"""交互式 Agent CLI 输入层测试。"""

from unittest.mock import MagicMock, patch

from rich.padding import Padding

from airouter.cli.agent import _configure_line_editing, _render_user_message


def test_configure_line_editing_enables_emacs_keys():
    readline = MagicMock()
    with patch("airouter.cli.agent._readline", readline):
        enabled = _configure_line_editing()

    assert enabled is True
    readline.parse_and_bind.assert_called_once_with("set editing-mode emacs")


def test_configure_line_editing_has_plain_input_fallback():
    with patch("airouter.cli.agent._readline", None):
        assert _configure_line_editing() is False


def test_render_user_message_replaces_typed_line_with_grey_block():
    console = MagicMock()
    console.is_terminal = True
    console.width = 80

    with patch("airouter.cli.agent.console", console):
        _render_user_message("请检查这个文件")

    console.file.write.assert_called_once_with("\x1b[1A\r\x1b[2K")
    console.file.flush.assert_called_once()
    rendered = console.print.call_args.args[0]
    assert isinstance(rendered, Padding)


def test_render_user_message_is_silent_outside_terminal():
    console = MagicMock()
    console.is_terminal = False

    with patch("airouter.cli.agent.console", console):
        _render_user_message("hello")

    console.print.assert_not_called()
