"""Claude Code CLI subprocess wrapper — replaces Anthropic SDK."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator


class ClaudeRunError(RuntimeError):
    """Raised when the claude CLI exits non-zero or times out."""


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
    cmd = ["claude", "-p", prompt]
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
) -> Iterator[str]:
    """
    Run `claude -p <prompt>` and yield stdout lines as they arrive.

    Useful for streaming output to the browser via SSE.

    Raises:
        ClaudeRunError: If claude exits non-zero after the stream ends.
    """
    cmd = ["claude", "-p", prompt]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    for raw_line in proc.stdout:
        line = raw_line.strip()
        if line:
            yield line

    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read().strip() if proc.stderr else ""
        raise ClaudeRunError(
            f"claude exited with exit code {proc.returncode}: {stderr}"
        )
