---
description: Implement an MCP component (tool/resource/prompt/middleware) efficiently
---

# Implement MCP Component

You are implementing a specific MCP component with a focused, efficient workflow.

## Arguments

- **filename**: The file path to implement (e.g., `src/tools/add_two_numbers.py`)
- **description**: What the component should do

## Your Task

Follow this streamlined workflow. Do NOT overthink it. Move quickly and efficiently.

### Step 1: Implement the Component

Read the file and implement the functionality as described.

**Key points:**
- Use proper type hints
- Add validation for inputs where appropriate
- Return meaningful error messages when things fail
- Keep it simple and focused
- The file already has the basic structure from the generator - just fill in the implementation

### Step 2: Update Tests

Find or create the corresponding test file in `tests/`:
- `src/tools/my_tool.py` → `tests/test_my_tool.py`
- `src/resources/my_resource.py` → `tests/test_my_resource.py`
- `src/prompts/my_prompt.py` → `tests/test_my_prompt.py`
- `src/middleware/my_middleware.py` → `tests/test_my_middleware.py`

Update the test to cover:
- Happy path (normal successful execution)
- Error cases (invalid inputs, edge cases)
- Type validation if applicable

**Testing Pattern Reminder:**
```python
from src.tools.my_tool import my_tool
my_tool_fn = my_tool.fn  # Access underlying function

@pytest.mark.asyncio
async def test_my_tool():
    result = await my_tool_fn(param="value")
    assert result == "expected"
```

### Step 3: Run the Tests

Run ONLY the specific test file you just updated:
```bash
pytest tests/test_<component_name>.py -v
```

If tests fail, fix them and re-run. Do not proceed until tests pass.

### Step 4: Done

Once tests pass, you're done. Report success with a brief summary.

## Important Guidelines

- **Do NOT overthink** - implement the straightforward solution
- **Do NOT add unnecessary complexity** - keep it simple
- **Do NOT skip tests** - always test your implementation
- **Do NOT test unrelated code** - run only the specific test file
- **Speed matters** - work efficiently through these steps

## Example Usage

```
/implement-mcp-item src/tools/add_two_numbers.py Make this take two values of any numeric type and add them together. Do good type checking and reject non-numeric values. Return error when possible.
```

Expected flow:
1. Implement the addition logic with type checking in the file
2. Update `tests/test_add_two_numbers.py` with test cases
3. Run `pytest tests/test_add_two_numbers.py -v`
4. Report success
