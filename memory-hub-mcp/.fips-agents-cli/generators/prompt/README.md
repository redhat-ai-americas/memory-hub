# Prompt Generator

Generate new MCP prompts for LLM interactions.

## Usage

```bash
fips-agents generate prompt <name> [options]
```

## Options

- `--with-schema` - Include JSON schema for structured output
- `--params "param1:str,param2:int"` - Define parameters
- `--description "..."` - Prompt description

## Examples

### Basic Prompt
```bash
fips-agents generate prompt summarize --description "Summarize text"
```

### Prompt with Schema
```bash
fips-agents generate prompt analyze-code --with-schema
```

### Prompt with Parameters
```bash
fips-agents generate prompt translate --params "text:str,target_language:str"
```

## Generated Files

- `src/prompts/<name>.py` - Prompt implementation
- `tests/prompts/test_<name>.py` - Prompt tests

## Template Variables

- `component_name` - Function name (snake_case)
- `description` - Prompt description
- `with_schema` - Include JSON schema
- `params` - Parameter definitions
- `project_name` - Project name

## Prompt Best Practices

1. **Clear instructions** - Be explicit about what the LLM should do
2. **Structured output** - Use JSON schemas when you need structured data
3. **Examples** - Include examples in prompts when helpful
4. **Context tags** - Use XML-style tags for content sections
5. **Parameter validation** - Use Pydantic Field for validation
