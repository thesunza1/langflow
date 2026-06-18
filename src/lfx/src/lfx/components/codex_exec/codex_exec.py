from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from lfx.custom.custom_component.component import Component
from lfx.io import BoolInput, IntInput, MessageTextInput, Output
from lfx.log.logger import logger
from lfx.schema.message import Message


class CodexExecComponent(Component):
    display_name = "Codex Exec"
    description = "Combine multiple text inputs and execute via Codex CLI."
    documentation = ""
    icon = "terminal"
    name = "CodexExec"

    inputs = [
        MessageTextInput(
            name="prompt_1",
            display_name="Prompt 1",
            info="First prompt. Supports connection from other nodes.",
            required=True,
        ),
        MessageTextInput(
            name="prompt_2",
            display_name="Prompt 2",
            info="Second prompt. Supports connection from other nodes.",
            required=True,
        ),
        MessageTextInput(
            name="prompt_3",
            display_name="Prompt 3",
            info="Third prompt (optional). Supports connection from other nodes.",
            required=False,
        ),
        MessageTextInput(
            name="prompt_4",
            display_name="Prompt 4",
            info="Fourth prompt (optional). Supports connection from other nodes.",
            required=False,
        ),
        MessageTextInput(
            name="directory",
            display_name="Directory",
            info="Working directory for Codex CLI. The path must exist on disk.",
            required=True,
        ),
        BoolInput(
            name="bypass_sandbox",
            display_name="Bypass Sandbox",
            info=(
                "\u26a0\ufe0f DANGER: When enabled, passes "
                "--dangerously-bypass-approvals-and-sandbox "
                "to Codex CLI. This bypasses all approvals and sandbox protections."
            ),
            value=False,
            advanced=True,
        ),
        MessageTextInput(
            name="timeout",
            display_name="Timeout (s)",
            info="Maximum time in seconds to wait for Codex CLI to complete.",
            value="6000",
            advanced=True,
        ),
        IntInput(
            name="max_output_length",
            display_name="Max Output Length",
            info=(
                "Maximum output length in characters. "
                "Set to 0 or negative for unlimited."
            ),
            value=500000,
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Result", name="result", method="execute"),
    ]

    def execute(self) -> Message:
        self.status = "Running..."

        # 1. Collect non-empty prompts
        prompts_raw = [
            getattr(self, "prompt_1", ""),
            getattr(self, "prompt_2", ""),
            getattr(self, "prompt_3", ""),
            getattr(self, "prompt_4", ""),
        ]
        prompts = [p.strip() for p in prompts_raw if p and p.strip()]
        if not prompts:
            self.status = "Error: no prompts"
            return Message(text="At least one prompt is required.")

        combined = " ".join(prompts)

        # 2. Validate directory
        try:
            dir_path = Path(self.directory).resolve()
            if not dir_path.is_dir():
                self.status = "Error: directory not found"
                return Message(text=f"Directory '{self.directory}' not found.")
        except Exception as e:
            self.status = "Error: invalid path"
            return Message(text=f"Invalid directory path: {e!s}")

        # 3. Check codex CLI
        codex_path = shutil.which("codex")
        if not codex_path:
            self.status = "Error: codex not found"
            return Message(text="'codex' command not found on PATH.")

        # 4. Create temp file for the last-message output
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".md")
            output_path = tmp.name
            tmp.close()
        except Exception as e:
            self.status = "Error: temp file"
            return Message(text=f"Failed to create temp file: {e!s}")

        # 5. Build command
        cmd = ["codex", "exec"]
        if self.bypass_sandbox:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        cmd += [combined, "-C", str(dir_path), "--output-last-message", output_path]

        # 6. Build a display string of the actual command
        cmd_display = " ".join(
            c if " " not in c else f'"{c}"' for c in cmd
        )
        # Truncate the prompt part for display
        if len(cmd_display) > 300:
            cmd_display = cmd_display[:300] + "..."
        self.status = f"Running: codex exec (dir={dir_path})"

        # 6. Execute with real-time log streaming
        import select as _select
        import time as _time

        timeout_secs = int(self.timeout)
        exit_code = None

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                shell=False,
            )
        except Exception as e:
            self._cleanup_temp(output_path)
            logger.exception(f"Failed to start codex exec: {e!s}")
            self.status = "Error: start"
            return Message(text=f"Failed to start Codex CLI: {e!s}")

        logger.info(f"Running: {cmd_display}")
        start_time = _time.time()
        stderr_lines: list[str] = []

        try:
            while True:
                # Check timeout
                elapsed = _time.time() - start_time
                if elapsed > timeout_secs:
                    process.kill()
                    process.wait()
                    self._cleanup_temp(output_path)
                    self.status = "Error: timeout"
                    return Message(text=f"Command timed out after {self.timeout}s.")

                # Use select to check which pipes have data ready
                rlist, _, _ = _select.select([process.stdout, process.stderr], [], [], 0.5)

                got_data = False

                for fd in rlist:
                    line = fd.readline()
                    if line:
                        got_data = True
                        text = line.rstrip("\n\r")
                        if fd is process.stderr:
                            stderr_lines.append(text)
                            self.log(text, name="codex:stderr")
                        else:
                            self.log(text, name="codex")
                        # Update running status with the latest line
                        display = text if len(text) <= 120 else text[:117] + "..."
                        elapsed = _time.time() - start_time
                        self.status = f"({elapsed:.1f}s) {display}"

                if not got_data and process.poll() is not None:
                    # Read any remaining lines
                    for line in process.stdout:
                        text = line.rstrip("\n\r")
                        self.log(text, name="codex")
                        display = text if len(text) <= 120 else text[:117] + "..."
                        elapsed = _time.time() - start_time
                        self.status = f"({elapsed:.1f}s) {display}"
                    for line in process.stderr:
                        text = line.rstrip("\n\r")
                        stderr_lines.append(text)
                        self.log(text, name="codex:stderr")
                        display = text if len(text) <= 120 else text[:117] + "..."
                        elapsed = _time.time() - start_time
                        self.status = f"({elapsed:.1f}s) {display}"
                    break

            exit_code = process.wait()

        except Exception as e:
            process.kill()
            process.wait()
            self._cleanup_temp(output_path)
            logger.exception(f"Codex exec failed: {e!s}")
            self.status = "Error"
            return Message(text=f"Execution error: {e!s}")

        # 7. Read the last-message output file
        try:
            output_path_obj = Path(output_path)
            if output_path_obj.exists():
                output = output_path_obj.read_text(encoding="utf-8").strip()
            else:
                output = ""
        except Exception as e:
            self._cleanup_temp(output_path)
            self.status = "Error: read output"
            return Message(text=f"Failed to read output: {e!s}")

        self._cleanup_temp(output_path)

        # 8. Prepend command info so user knows what was executed
        cmd_parts = ["codex", "exec"]
        if self.bypass_sandbox:
            cmd_parts.append("--dangerously-bypass-approvals-and-sandbox")
        prompt_preview = combined if len(combined) <= 120 else combined[:120] + "..."
        cmd_parts.append(f'"{prompt_preview}"')
        cmd_parts.extend(["-C", str(dir_path)])
        cmd_summary = "> " + " ".join(cmd_parts) + "\n"
        output = cmd_summary + output

        # 9. Fallback: if no output file, use stderr
        if not output.strip() and stderr_lines:
            output = cmd_summary + "\n".join(stderr_lines)

        # 10. Truncate if needed
        try:
            max_len = int(getattr(self, "max_output_length", 500000))
        except (ValueError, TypeError):
            max_len = 500000

        if max_len > 0 and len(output) > max_len:
            output = output[:max_len] + "\n\n... [Output truncated]"

        self.status = f"Done (exit code {exit_code})"
        return Message(text=output)

    @staticmethod
    def _cleanup_temp(path: str) -> None:
        """Safely remove a temp file."""
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
