"""Tests for claude_runner subprocess wrapper."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.utils.claude_runner import ClaudeRunError, run_claude, stream_claude


class TestRunClaude:
    def test_returns_stdout_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "scored: 85\nreasoning: good fit"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = run_claude("evaluate this job")

        assert result == "scored: 85\nreasoning: good fit"
        mock_run.assert_called_once()

    def test_raises_on_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "claude: command not found"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ClaudeRunError, match="exit code 1"):
                run_claude("evaluate this job")

    def test_passes_prompt_as_p_flag(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_claude("my prompt")

        cmd = mock_run.call_args[0][0]
        assert "claude" in cmd[0].lower()
        assert "-p" in cmd
        prompt_idx = cmd.index("-p")
        assert cmd[prompt_idx + 1] == "my prompt"

    def test_includes_allowed_tools_when_specified(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_claude("my prompt", tools=["WebSearch", "WebFetch"])

        cmd = mock_run.call_args[0][0]
        assert "--allowedTools" in cmd
        tools_idx = cmd.index("--allowedTools")
        assert cmd[tools_idx + 1] == "WebSearch,WebFetch"

    def test_no_allowed_tools_flag_when_tools_is_none(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_claude("my prompt", tools=None)

        cmd = mock_run.call_args[0][0]
        assert "--allowedTools" not in cmd

    def test_strips_trailing_whitespace_from_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  result with spaces  \n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = run_claude("prompt")

        assert result == "result with spaces"

    def test_timeout_passed_to_subprocess(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_claude("prompt", timeout=30)

        kwargs = mock_run.call_args[1]
        assert kwargs.get("timeout") == 30

    def test_raises_claude_run_error_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 30)):
            with pytest.raises(ClaudeRunError, match="timed out"):
                run_claude("prompt", timeout=30)


class TestStreamClaude:
    def test_yields_lines_from_stdout(self):
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line one\n", "line two\n", "line three\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            lines = list(stream_claude("my prompt"))

        assert lines == ["line one", "line two", "line three"]

    def test_raises_on_nonzero_exit_after_stream(self):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            with pytest.raises(ClaudeRunError):
                list(stream_claude("my prompt"))

    def test_skips_empty_lines(self):
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["word\n", "\n", "another\n", "   \n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            lines = list(stream_claude("my prompt"))

        assert lines == ["word", "another"]
