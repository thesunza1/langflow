"""Unit tests for CodexExecComponent."""
from __future__ import annotations

import shutil

from lfx.components.codex_exec.codex_exec import CodexExecComponent


class TestCodexExecComponent:
    """Test suite for CodexExecComponent."""

    def test_instantiation(self):
        comp = CodexExecComponent()
        assert comp.display_name == "Codex Exec"
        assert comp.description == "Combine multiple text inputs and execute via Codex CLI."
        assert comp.icon == "terminal"
        assert comp.name == "CodexExec"

    def test_inputs_and_outputs(self):
        comp = CodexExecComponent()
        input_names = {i.name for i in comp.inputs}
        assert input_names == {"prompt_1", "prompt_2", "prompt_3", "prompt_4",
                               "directory", "bypass_sandbox", "timeout"}
        output_names = {o.name for o in comp.outputs}
        assert output_names == {"result"}

    def test_execute_empty_prompts(self):
        comp = CodexExecComponent()
        comp.prompt_1 = ""
        comp.prompt_2 = ""
        comp.prompt_3 = ""
        comp.prompt_4 = ""
        comp.directory = "/tmp"
        comp.bypass_sandbox = False
        comp.timeout = "6000"
        result = comp.execute()
        assert "At least one prompt" in result.text
        assert comp.status == "Error: no prompts"

    def test_execute_invalid_directory(self):
        comp = CodexExecComponent()
        comp.prompt_1 = "test"
        comp.prompt_2 = "prompt"
        comp.directory = "/nonexistent_path_for_testing"
        result = comp.execute()
        assert "not found" in result.text

    def test_execute_codex_not_found(self, monkeypatch):
        monkeypatch.setattr(shutil, "which",
                            lambda cmd: None if cmd == "codex" else f"/usr/bin/{cmd}")
        comp = CodexExecComponent()
        comp.prompt_1 = "test"
        comp.prompt_2 = "prompt"
        comp.directory = "/tmp"
        result = comp.execute()
        assert "codex" in result.text.lower()

    def test_message_output_type(self):
        """Result output should return Message type for compatibility."""
        from lfx.schema.message import Message
        comp = CodexExecComponent()
        result = comp.execute()
        assert isinstance(result, Message)
