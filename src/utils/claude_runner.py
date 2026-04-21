"""Claude Code CLI subprocess wrapper — replaces Anthropic SDK."""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Iterator


class ClaudeRunError(RuntimeError):
    """Raised when the claude CLI exits non-zero or times out."""


def _find_claude() -> str:
    """
    Resolve the full path to the claude CLI executable.

    On Windows, npm installs claude as claude.CMD which subprocess cannot
    find by bare name without shell=True. shutil.which resolves the full
    path including extension, making the subprocess call portable.
    """
    path = shutil.which("claude")
    if not path:
        raise ClaudeRunError(
            "claude CLI not found on PATH. "
            "Install Claude Code from https://claude.ai/code and ensure it is on your PATH."
        )
    return path


_CLAUDE_CMD = _find_claude()


def run_claude(
    prompt: str,
    tools: list[str] | None = None,
    timeout: int = 120,
) -> str:
    """
    Run `claude -p <prompt>` and return stdout as a string.

    Args:
        prompt: The prompt to send to Claude.
        tools: If provided, passed as `--allowedTools Tool1,Tool2`.
        timeout: Seconds before raising ClaudeRunError.

    Returns:
        Stripped stdout from Claude.

    Raises:
        ClaudeRunError: On non-zero exit or timeout.
    """
    cmd = [_CLAUDE_CMD, "-p", prompt]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeRunError(f"claude timed out after {timeout}s")

    if result.returncode != 0:
        raise ClaudeRunError(
            f"claude exited with exit code {result.returncode}: {result.stderr.strip()}"
        )

    return result.stdout.strip()


def stream_claude(
    prompt: str,
    tools: list[str] | None = None,
    timeout: int = 300,
) -> Iterator[str]:
    """
    Run `claude -p <prompt>` and yield stdout lines as they arrive.

    Useful for streaming output to the browser via SSE.

    Args:
        prompt: The prompt to send to Claude.
        tools: If provided, passed as `--allowedTools Tool1,Tool2`.
        timeout: Seconds before raising ClaudeRunError (default 300).

    Raises:
        ClaudeRunError: If claude exits non-zero or times out.
    """
    cmd = [_CLAUDE_CMD, "-p", prompt]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_lines.append(line)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    try:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if line:
                yield line
    finally:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise ClaudeRunError(f"claude timed out after {timeout}s")
        stderr_thread.join(timeout=5)

    if proc.returncode != 0:
        stderr = "".join(stderr_lines).strip()
        raise ClaudeRunError(
            f"claude exited with exit code {proc.returncode}: {stderr}"
        )
