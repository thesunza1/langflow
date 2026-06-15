from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lfx.custom.custom_component.component import Component
from lfx.io import BoolInput, MessageTextInput, Output
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
            info="⚠️ DANGER: When enabled, passes --dangerously-bypass-approvals-and-sandbox "
            "to Codex CLI. This bypasses all approvals and sandbox protections.",
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

        # 4. Build command
        cmd = ["codex", "exec"]
        if self.bypass_sandbox:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        cmd += [combined, "--DIR", str(dir_path)]

        # 5. Execute
        try:
            logger.info(f"Running codex exec in {dir_path}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(self.timeout),
                shell=False,
            )

            output = result.stdout.strip()
            if result.stderr.strip():
                output += "\n\n[STDERR]\n" + result.stderr.strip()

            max_len = 100000
            if len(output) > max_len:
                output = output[:max_len] + "\n\n... [Output truncated]"

            self.status = f"Done (exit code {result.returncode})"
            return Message(text=output)

        except subprocess.TimeoutExpired:
            self.status = "Error: timeout"
            return Message(text=f"Command timed out after {self.timeout}s.")
        except Exception as e:
            logger.exception(f"Codex exec failed: {e!s}")
            self.status = "Error"
            return Message(text=f"Execution error: {e!s}")
