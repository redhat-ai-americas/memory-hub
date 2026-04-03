# AI Coding Assistant Guidelines

This file provides guidance for AI coding assistants (Claude, Cursor, GitHub Copilot, etc.) working with this MCP server template.

## MCP Development Workflow

This template provides a structured workflow for developing MCP tools. If using Claude Code, use the slash commands. For other assistants, follow this sequence manually:

### Recommended Sequence

```
1. Plan Tools      →  Create TOOLS_PLAN.md (planning only, no code)
2. Create Tools    →  Generate scaffolds, implement in parallel
3. Exercise Tools  →  Test ergonomics by role-playing as consumer
4. Deploy (opt.)   →  Deploy to OpenShift if needed
```

### Step 1: Plan Tools

Before writing any code:
1. Read Anthropic's tool design guidance: https://www.anthropic.com/engineering/writing-tools-for-agents
2. Review any existing proposal or requirements
3. Create `TOOLS_PLAN.md` with tool specifications including:
   - Tool name and purpose
   - Parameters with types and descriptions
   - Return values
   - Error cases
   - Example usage

### Step 2: Create Tools

For each tool in `TOOLS_PLAN.md`:
1. Generate scaffold: `fips-agents generate tool <name> --description "<desc>" --async --with-context`
2. Implement the tool in `src/tools/<name>.py`
3. Update tests in `tests/test_<name>.py`
4. Run tests: `.venv/bin/pytest tests/test_<name>.py -v`

**Note**: `fips-agents` is a global CLI tool (installed via pipx) - run it directly without any venv prefix. Only `pytest` and other project dependencies use `.venv/bin/`.

### Step 3: Exercise Tools

Test usability by role-playing as the agent that will consume these tools:
- Are parameter names intuitive?
- Do error messages help with recovery?
- Do tools compose well together?

### Step 4: Deploy (Optional)

Before deployment:
1. Fix permissions: `find src -name "*.py" -perm 600 -exec chmod 644 {} \;`
2. Run all tests: `.venv/bin/pytest tests/ -v --ignore=tests/examples/`
3. Deploy: `make deploy PROJECT=<server-name>`
4. Verify with `mcp-test-mcp` if available

### Import Convention

**IMPORTANT**: Always use the `src.` prefix for all imports:

```python
# Correct
from src.core.app import mcp
from src.tools.my_tool import my_tool

# Incorrect - creates dual namespace issues
from core.app import mcp
from tools.my_tool import my_tool
```

## Project Structure and Testing Patterns

### Testing FastMCP Decorated Functions

**IMPORTANT**: FastMCP decorators (`@mcp.tool`, `@mcp.resource`, `@mcp.prompt`) wrap functions in special objects. To test these functions directly, you must access the underlying function using the `.fn` attribute.

**Correct Testing Pattern**:
```python
# In tests/tools/test_my_tool.py
from src.tools.my_tool import my_tool

# Access the underlying function
my_tool_fn = my_tool.fn

@pytest.mark.asyncio
async def test_my_tool():
    result = await my_tool_fn(param1="value1", param2="value2")
    assert result == "expected"
```

**Why This Matters**: Attempting to call decorated functions directly in tests will fail because the decorator returns a `FunctionTool`, `Resource`, or `Prompt` object, not the original function.

### Dependency Management

**CRITICAL**: All Python dependencies must be listed in BOTH `pyproject.toml` AND `requirements.txt`.

- `pyproject.toml`: For local development with `pip install -e .`
- `requirements.txt`: For container builds and OpenShift deployments

**When adding a new dependency**:
1. Add it to `pyproject.toml` under `dependencies`
2. Add it to `requirements.txt` with the same version constraint
3. Run `pip install -e .` to install locally
4. Test that the container build works: `podman build --platform linux/amd64 -f Containerfile -t test:latest .`

**Example**:
```toml
# In pyproject.toml
dependencies = [
    "fastmcp>=2.11.3",
    "httpx>=0.27.0",  # <-- New dependency
]
```

```txt
# In requirements.txt
fastmcp>=2.11.3
httpx>=0.27.0  # <-- Same dependency
```

### Template Structure

This template uses a **multi-module structure** under `src/`:

```
src/
├── core/           # Core MCP server setup
├── middleware/     # Request/response middleware
├── prompts/        # YAML-based prompt definitions
├── resources/      # MCP resources
├── tools/          # MCP tools
└── main.py         # Entry point
```

**Key Points**:
- No single module directory (not `src/my_project_name/`)
- Prompts are under `src/prompts/` (NOT at project root)
- The Containerfile copies the entire `src/` directory
- Entry point is `src.main:main` (not `src.my_project_name.main:main`)

### Container Build Considerations

The `Containerfile`:
- Uses Red Hat UBI9 Python 3.11 base image
- Copies `requirements.txt` first for layer caching
- Copies `src/` directory (which includes `src/prompts/`)
- Runs as non-root user (1001)
- Expects HTTP transport on port 8080

**Building for OpenShift**:
```bash
podman build --platform linux/amd64 -f Containerfile -t my-mcp:latest .
```

Always specify `--platform linux/amd64` when building on Mac to avoid ARM64/x86_64 architecture mismatches in OpenShift.

## Important Notes

* Your internal knowledgebase of libraries might not be up to date. When working with any external library, unless you are 100% sure that the library has a super stable interface, you will look up the latest syntax and usage via **context7**
* Do not say things like: "x library isn't working so I will skip it". Generally, it isn't working because you are using the incorrect syntax or patterns. This applies doubly when the user has explicitly asked you to use a specific library, if the user wanted to use another library they wouldn't have asked you to use a specific one in the first place.
* Always run linting after making major changes. Otherwise, you won't know if you've corrupted a file or made syntax errors, or are using the wrong methods, or using methods in the wrong way.
* Please organize code into separate files wherever appropriate, and follow general coding best practices about variable naming, modularity, function complexity, file sizes, commenting, etc.
* Keep files small, aiming for fewer than 512 lines of code where possible
* A small file that imports other small files is preferred over one large file
* Code is read more often than it is written, make sure your code is always optimized for readability
* Unless explicitly asked otherwise, the user never wants you to do a "dummy" implementation of any given task. Never do an implementation where you tell the user: "This is how it *would* look like". Just implement the thing.
* Whenever you are starting a new task, it is of utmost importance that you have clarity about the task. You should ask the user follow up questions if you do not, rather than making incorrect assumptions.
* Do not carry out large refactors unless explicitly instructed to do so.
* When starting on a new task, you should first understand the current architecture, identify the files you will need to modify, and come up with a Plan. In the Plan, you will think through architectural aspects related to the changes you will be making, consider edge cases, and identify the best approach for the given task. Get your Plan approved by the user before writing a single line of code.
* If you are running into repeated issues with a given task, figure out the root cause instead of throwing random things at the wall and seeing what sticks, or throwing in the towel by saying "I'll just use another library / do a dummy implementation".
* Consult with the user for feedback when needed, especially if you are running into repeated issues or blockers. It is very rewarding to consult the user when needed as it shows you are a good team player.
* You are an incredibly talented and experienced polyglot with decades of experience in diverse areas such as software architecture, system design, development, UI & UX, copywriting, and more.
* When doing UI & UX work, make sure your designs are both aesthetically pleasing, easy to use, and follow UI / UX best practices. You pay attention to interaction patterns, micro-interactions, and are proactive about creating smooth, engaging user interfaces that delight users.
* When you receive a task that is very large in scope or too vague, you will first try to break it down into smaller subtasks. If that feels difficult or still leaves you with too many open questions, push back to the user and ask them to consider breaking down the task for you, or guide them through that process. This is important because the larger the task, the more likely it is that things go wrong, wasting time and energy for everyone involved.
* When you are asked to make a change to a program, make the change in the existing file unless specifically instructed otherwise.
* When adding or changing UI features, be mindful about existing functionality that already works.
* When designing complex UI, break things into separate files that make editing one part of the UI straightforward and limit undesired changes.
* When I say "let's discuss" or "let's talk about this" or "create a plan" or similar, I want you to not create or change any code in this turn. I am wanting to have a conversation about the plan ahead. Do not move directly to implementation for that turn. Give me a chance to weigh in and tell you what I want.
* If I give you an MCP server URL to use with an agent, do not try to test the MCP server yourself. Just use it with the agent and let the agent discover its tools. This is different from a REST API where I would want you to curl the endpoints to verify they work. With MCP servers, I will have already verified that it works using a different tool, and I need you to integrate it with the agent. If you need to know the names of the tools ahead of time, you can ask me and I can provide them to you.
* When using MCP servers, be sure we have a valid MCP client, and let FastMCP auto-detect the transport. Trust the process on this and don't overthink it. This is not the same as a regular API.
* If I ask you "Can we do X?" I really do just want you to answer that question, giving me enough detail to understand the answer and make a decision. I do NOT mean "answer user briefly and then run off and implement X." This is important because sometimes I may have a follow-up question in mind, or want to discuss implementation steps prior to us actually doing the implementation.

## Prompt Parameter Types (FastMCP 2.9.0+)

### Supported Type Annotations

When defining prompt parameters, use these type patterns:

**Simple Types**:
- `str`, `int`, `float`, `bool`

**List Types** (must be parameterized):
- `list[str]`, `list[int]`, `list[float]`

**Dict Types** (must be parameterized):
- `dict[str, str]` - String keys and values
- `dict[str, Any]` - String keys, any JSON-serializable values
- `dict[str, int]`, `dict[str, float]`, etc.

**Optional Types** (use union syntax):
- `str | None`, `int | None`, `dict[str, str] | None`

⚠️ **Important**: Never use bare `dict` or `list` without type parameters.
FastMCP requires parameterized types to generate proper JSON schema hints for clients.

### Pattern: Field() with Defaults

```python
@mcp.prompt
def my_prompt(
    # Required parameter
    data: dict[str, str] = Field(
        description="Data dictionary (required)"
    ),

    # Optional parameter with default
    format: str = Field(
        default="json",
        description="Output format: 'json' or 'text'"
    ),

    # Optional parameter that can be None
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata dictionary"
    ),
) -> str:
    """Your prompt docstring."""
    return f"..."
```

### Why These Patterns Matter

1. **MCP Protocol Requirement**: MCP clients pass all arguments as strings
2. **FastMCP Conversion**: FastMCP auto-converts JSON strings to typed objects
3. **Schema Generation**: Parameterized types enable automatic schema hints
4. **Client Guidance**: Generated schemas tell clients the expected JSON format

### Example: MCP Client Usage

When you define:
```python
data: dict[str, str] = Field(description="User data")
```

FastMCP generates this for MCP clients:
```json
{
  "name": "data",
  "description": "User data\n\nProvide as JSON string matching: {\"additionalProperties\":{\"type\":\"string\"},\"type\":\"object\"}",
  "required": true
}
```

Clients then pass:
```json
{
  "data": "{\"name\": \"John\", \"email\": \"john@example.com\"}"
}
```

FastMCP automatically converts the JSON string to a Python dict.

## Prompt Generation Options (FastMCP 2.x)

### Return Types

Prompts can return different types based on use case:

**`str` (default)**: Simple string prompt
```python
@mcp.prompt
def simple_prompt(query: str = Field(description="User query")) -> str:
    return f"Please answer: {query}"
```

**`PromptMessage`**: Structured message with role
```python
from fastmcp.prompts.prompt import PromptMessage, TextContent

@mcp.prompt
def structured_prompt(query: str = Field(description="User query")) -> PromptMessage:
    content = f"Please answer: {query}"
    return PromptMessage(
        role="user",
        content=TextContent(type="text", text=content)
    )
```

**`list[PromptMessage]`**: Multi-turn conversation
```python
from fastmcp.prompts.prompt import Message

@mcp.prompt
def conversation(topic: str = Field(description="Discussion topic")) -> list[PromptMessage]:
    return [
        Message(f"Let's discuss {topic}"),
        Message("That's interesting!", role="assistant"),
        Message("What do you think about...?")
    ]
```

### Async Prompts

Use async prompts when performing I/O operations:

```python
import aiohttp

@mcp.prompt
async def fetch_prompt(url: str = Field(description="Data source URL")) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.text()
    return f"Analyze this data: {data}"
```

Generate with: `fips-agents generate prompt fetch_data --async`

### Context Access

Access MCP context for request metadata and features:

```python
from fastmcp import Context

@mcp.prompt
def tracked_prompt(
    query: str = Field(description="User query"),
    ctx: Context,
) -> str:
    return f"""Query: {query}
Request ID: {ctx.request_id}

Please provide a detailed response."""
```

Generate with: `fips-agents generate prompt my_prompt --with-context`

### Decorator Arguments

Customize prompt metadata:

```python
@mcp.prompt(
    name="custom_name",
    title="Human Readable Title",
    description="Custom description",
    tags={"category", "type"},
    enabled=True,
    meta={"version": "1.0", "author": "team"}
)
def my_prompt(data: str = Field(description="Input data")) -> str:
    return f"Process: {data}"
```

Generate with:
```bash
fips-agents generate prompt my_prompt \
    --prompt-name "custom_name" \
    --title "Human Readable Title" \
    --tags "category,type" \
    --meta '{"version": "1.0"}'
```

### CLI Examples

**Basic Prompt**:
```bash
fips-agents generate prompt summarize_text \
    --description "Summarize text content"
```

**Async Prompt with Context**:
```bash
fips-agents generate prompt fetch_and_analyze \
    --async \
    --with-context \
    --return-type PromptMessage \
    --description "Fetch and analyze data asynchronously"
```

**Prompt with Parameters**:
```bash
# Create params.json
cat > params.json << 'EOF'
[
  {
    "name": "data",
    "type": "dict[str, str]",
    "description": "Data to analyze",
    "required": true
  },
  {
    "name": "analysis_type",
    "type": "str",
    "description": "Type of analysis",
    "default": "\"summary\"",
    "required": false
  }
]
EOF

fips-agents generate prompt analyze_data \
    --params params.json \
    --with-schema \
    --return-type "list[PromptMessage]"
```

**Advanced Prompt with Metadata**:
```bash
fips-agents generate prompt report_generator \
    --async \
    --with-context \
    --prompt-name "generate_report" \
    --title "Report Generator" \
    --tags "reporting,analysis,business" \
    --meta '{"version": "2.0", "author": "data-team"}' \
    --description "Generate comprehensive business reports"
```
