import sys
from pathlib import Path

from src.core.app import mcp
from src.core.loaders import load_tools, load_resources, load_prompts


def test_load_tools_resources_prompts(tmp_path: Path):
    # Create temp dirs that mimic project layout
    src_base = tmp_path / "src"
    tools_dir = src_base / "tools"
    resources_dir = src_base / "resources"
    prompts_dir = tmp_path / "prompts"

    tools_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)

    # Write a simple tool
    (tools_dir / "t1.py").write_text(
        "from src.core.app import mcp\nfrom fastmcp import Context\n@mcp.tool\nasync def t1(x: int, ctx: Context) -> int:\n    await ctx.debug('adding one')\n    return x + 1\n"
    )

    # Write a simple resource
    (resources_dir / "r1.py").write_text(
        "from src.core.app import mcp\n@mcp.resource(\"resource://r1\")\ndef r1() -> str:\n    return 'ok'\n"
    )

    # Write a simple prompt (Python-based with FastMCP decorator)
    (prompts_dir / "p1.py").write_text(
        "from src.core.app import mcp\n"
        "from pydantic import Field\n\n"
        "@mcp.prompt\n"
        "def demo(name: str = Field(description='Name to greet')) -> str:\n"
        "    return f'Hello {name}'\n"
    )

    # Ensure import path includes temp directory so src.* imports work
    sys.path.insert(0, str(tmp_path))

    c1 = load_tools(mcp, tools_dir)
    c2 = load_resources(mcp, resources_dir)
    c3 = load_prompts(mcp, prompts_dir)

    assert c1 >= 1
    assert c2 >= 1
    assert c3 >= 1
