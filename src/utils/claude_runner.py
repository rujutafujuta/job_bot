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
    Run `claude -p` with the prompt piped via stdin and return stdout.

    Stdin is used instead of passing the prompt as a CLI argument to avoid
    Windows batch-file (.CMD) shell parsing mangling special characters
    (parentheses, pipes, angle brackets, etc.) that appear in Markdown CVs
    and other structured text.

    Args:
        prompt: The prompt to send to Claude.
        tools: If provided, passed as `--allowedTools Tool1,Tool2`.
        timeout: Seconds before raising ClaudeRunError.

    Returns:
        Stripped stdout from Claude.

    Raises:
        ClaudeRunError: On non-zero exit or timeout.
    """
    cmd = [_CLAUDE_CMD, "-p"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ClaudeRunError(f"claude timed out after {timeout}s")

    output = result.stdout.strip()

    if result.returncode != 0:
        # A non-zero exit can be caused by post-session hooks (e.g. memory plugins)
        # failing AFTER Claude has already written its response to stdout.
        # If we have output, use it; only raise when stdout is empty.
        if not output:
            raise ClaudeRunError(
                f"claude exited with exit code {result.returncode}: {result.stderr.strip()}"
            )

    return output


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
    cmd = [_CLAUDE_CMD, "-p"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.stdin:
        proc.stdin.write(prompt)
        proc.stdin.close()

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
        # Hook failures after streaming produce non-zero exit but valid output was
        # already yielded. Only raise when the failure looks real (non-hook stderr).
        stderr = "".join(stderr_lines).strip()
        hook_failure = "hook" in stderr.lower() and "cancelled" in stderr.lower()
        if not hook_failure:
            raise ClaudeRunError(
                f"claude exited with exit code {proc.returncode}: {stderr}"
            )
