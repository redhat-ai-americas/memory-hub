"""
Tests for FastMCP compliance in tool implementations.

This test suite validates that tools follow FastMCP best practices.
"""

import sys
from pathlib import Path
import ast
import inspect

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


def get_function_source(module_path: Path, function_name: str):
    """Extract function source code from a module."""
    with open(module_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ):
            return node
    return None


def has_annotated_params(func_node):
    """Check if function has Annotated parameter types."""
    for arg in func_node.args.args:
        if arg.annotation and isinstance(arg.annotation, ast.Subscript):
            if (
                hasattr(arg.annotation.value, "id")
                and arg.annotation.value.id == "Annotated"
            ):
                return True
    return False


def has_context_param(func_node):
    """Check if function has Context parameter."""
    for arg in func_node.args.args:
        if arg.arg == "ctx":
            return True
    return False


class TestToolsCompliance:
    """Test that tools follow FastMCP best practices."""

    def test_echo_has_annotated_params(self):
        """Test echo tool has Annotated parameter descriptions."""
        src_path = Path(__file__).parent.parent / "src" / "tools" / "examples" / "echo.py"
        func = get_function_source(src_path, "echo")
        assert func is not None
        assert has_annotated_params(func), "echo should use Annotated for parameters"

    def test_echo_has_context(self):
        """Test echo tool has Context parameter."""
        src_path = Path(__file__).parent.parent / "src" / "tools" / "examples" / "echo.py"
        func = get_function_source(src_path, "echo")
        assert func is not None
        assert has_context_param(func), "echo should have ctx: Context parameter"

    def test_write_release_notes_has_annotated_params(self):
        """Test write_release_notes has Annotated parameters."""
        src_path = Path(__file__).parent.parent / "src" / "tools" / "examples" / "needs_sampling.py"
        func = get_function_source(src_path, "write_release_notes")
        assert func is not None
        assert has_annotated_params(func), "write_release_notes should use Annotated"

    def test_get_weather_has_annotated_params(self):
        """Test get_weather has Annotated parameters."""
        src_path = (
            Path(__file__).parent.parent / "src" / "tools" / "examples" / "needs_elicitation.py"
        )
        func = get_function_source(src_path, "get_weather")
        assert func is not None
        assert has_annotated_params(func), "get_weather should use Annotated"

    def test_advanced_examples_file_exists(self):
        """Test advanced_examples.py exists."""
        src_path = (
            Path(__file__).parent.parent / "src" / "tools" / "examples" / "advanced_examples.py"
        )
        assert src_path.exists(), "advanced_examples.py should exist"

    def test_advanced_examples_has_expected_functions(self):
        """Test advanced_examples.py has all expected demonstration functions."""
        src_path = (
            Path(__file__).parent.parent / "src" / "tools" / "examples" / "advanced_examples.py"
        )

        with open(src_path) as f:
            content = f.read()

        # Check for expected function names
        expected_functions = [
            "process_data",
            "validate_input",
            "analyze_text",
            "configure_system",
            "calculate_statistics",
            "format_text",
        ]

        for func_name in expected_functions:
            assert (
                f"def {func_name}" in content or f"async def {func_name}" in content
            ), f"advanced_examples.py should have {func_name} function"

    def test_advanced_examples_imports_field(self):
        """Test advanced_examples.py imports Field from pydantic."""
        src_path = (
            Path(__file__).parent.parent / "src" / "tools" / "examples" / "advanced_examples.py"
        )

        with open(src_path) as f:
            content = f.read()

        assert (
            "from pydantic import Field" in content
        ), "advanced_examples.py should import Field for validation"

    def test_advanced_examples_imports_tool_error(self):
        """Test advanced_examples.py imports ToolError."""
        src_path = (
            Path(__file__).parent.parent / "src" / "tools" / "examples" / "advanced_examples.py"
        )

        with open(src_path) as f:
            content = f.read()

        assert (
            "from fastmcp.exceptions import ToolError" in content
        ), "advanced_examples.py should import ToolError"

    def test_advanced_examples_has_dataclass(self):
        """Test advanced_examples.py defines structured output dataclass."""
        src_path = (
            Path(__file__).parent.parent / "src" / "tools" / "examples" / "advanced_examples.py"
        )

        with open(src_path) as f:
            content = f.read()

        assert (
            "@dataclass" in content
        ), "advanced_examples.py should demonstrate structured output with dataclass"

    def test_no_context_none_checks(self):
        """Test that tools don't check for ctx is None (FastMCP guarantees injection)."""
        tools_dir = Path(__file__).parent.parent / "src" / "tools"

        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name == "__init__.py":
                continue

            with open(tool_file) as f:
                content = f.read()

            # This is now acceptable - we allow ctx: Context = None but don't need defensive checks
            # The pattern ctx: Context = None is OK, checking for None is not needed
            assert (
                "if ctx is None:" not in content
            ), f"{tool_file.name} should not check 'if ctx is None' - FastMCP guarantees injection"

    def test_tools_use_type_hints(self):
        """Test that all tool files use proper type hints."""
        tools_dir = Path(__file__).parent.parent / "src" / "tools" / "examples"

        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name == "__init__.py" or tool_file.name == "README.md":
                continue  # Skip __init__.py and docs

            with open(tool_file) as f:
                content = f.read()

            # Check for typing imports (Annotated, etc.)
            has_typing = "from typing import" in content or "import typing" in content

            # Check for Context import
            has_context = "from fastmcp import Context" in content

            assert has_typing, f"{tool_file.name} should import from typing module"
            assert has_context, f"{tool_file.name} should import Context from fastmcp"


class TestDocumentation:
    """Test that documentation exists and is complete."""

    def test_tools_guide_exists(self):
        """Test TOOLS_GUIDE.md exists."""
        guide_path = Path(__file__).parent.parent / "docs" / "TOOLS_GUIDE.md"
        assert guide_path.exists(), "docs/TOOLS_GUIDE.md should exist"

    def test_tools_guide_has_key_sections(self):
        """Test TOOLS_GUIDE.md has all key sections."""
        guide_path = Path(__file__).parent.parent / "docs" / "TOOLS_GUIDE.md"

        with open(guide_path) as f:
            content = f.read()

        expected_sections = [
            "Type Hints and Descriptions",
            "Tool Annotations",
            "Field Validation",
            "Error Handling",
            "Structured Outputs",
            "Context Usage",
        ]

        for section in expected_sections:
            assert section in content, f"TOOLS_GUIDE.md should have {section} section"

    def test_readme_mentions_tools_guide(self):
        """Test README.md links to TOOLS_GUIDE.md."""
        readme_path = Path(__file__).parent.parent / "README.md"

        with open(readme_path) as f:
            content = f.read()

        assert "TOOLS_GUIDE.md" in content, "README.md should reference TOOLS_GUIDE.md"

    def test_architecture_mentions_best_practices(self):
        """Test ARCHITECTURE.md documents FastMCP best practices."""
        arch_path = Path(__file__).parent.parent / "ARCHITECTURE.md"

        with open(arch_path) as f:
            content = f.read()

        keywords = [
            "Annotated",
            "Field",
            "Tool Annotations",
            "readOnlyHint",
            "ToolError",
        ]

        for keyword in keywords:
            assert keyword in content, f"ARCHITECTURE.md should mention {keyword}"
