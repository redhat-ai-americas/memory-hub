# Generator System

This directory contains Jinja2 templates used by the `fips-agents generate` command to scaffold new MCP components.

**Note**: `fips-agents` is a global CLI tool installed via pipx. Run it directly - do NOT use `.venv/bin/fips-agents`. Only project dependencies like `pytest` use the `.venv/bin/` prefix.

## How It Works

When you run a generate command like:
```bash
fips-agents generate tool my-tool --async --with-context
```

The CLI:
1. Locates the appropriate template in `generators/<type>/`
2. Renders the template with your provided variables
3. Writes the generated component to `src/<type>/`
4. Creates a test file in `tests/<type>/`

## Template Structure

Each component type has its own directory:
- `tool/` - Tool component templates
- `resource/` - Resource component templates
- `prompt/` - Prompt component templates
- `middleware/` - Middleware component templates

Each directory contains:
- `component.py.j2` - Main component implementation template
- `test.py.j2` - Test file template
- `README.md` - Component-specific documentation

## Customizing Templates

You can customize these templates to match your project's conventions:

1. **Modify existing templates** - Edit `.j2` files to change generated code
2. **Add new variables** - Use Jinja2 syntax: `{{ variable_name }}`
3. **Add conditionals** - Use `{% if condition %}...{% endif %}`
4. **Update documentation** - Edit README files to guide your team

### Example Customization

If you want all tools to include a custom header comment:

```python
# component.py.j2
"""{{ description }}

Generated: {{ generation_date }}
Project: {{ project_name }}
"""

from typing import Annotated
from core.app import mcp
# ... rest of template
```

## Template Variables

All templates have access to these base variables:

### Common Variables
- `component_name` - Function/component name (snake_case)
- `component_class_name` - Class name if needed (PascalCase)
- `description` - Component description
- `project_name` - Project name
- `generation_date` - ISO format date/time

### Tool-Specific Variables
- `async` - Boolean, true for async functions
- `with_context` - Boolean, include FastMCP Context parameter
- `with_auth` - Boolean, include authentication decorator
- `read_only` - Boolean, mark as read-only operation
- `idempotent` - Boolean, mark as idempotent
- `open_world` - Boolean, can interact with external systems
- `params` - List of parameter definitions

### Resource-Specific Variables
- `uri` - Resource URI (e.g., "resource://my-resource")
- `mime_type` - MIME type for the resource
- `async` - Boolean, true for async resources

### Prompt-Specific Variables
- `with_schema` - Boolean, include JSON schema in prompt
- `params` - List of parameter definitions

### Middleware-Specific Variables
- `async` - Boolean, true for async middleware
- `hook_type` - Hook point (before_tool, after_tool, on_error)

## Parameter Definitions

The `params` variable is a list of dictionaries with:
```python
{
    "name": "param_name",
    "type": "str",  # Python type annotation
    "description": "Parameter description",
    "required": True,
    "default": None  # or default value
}
```

## Jinja2 Template Examples

### Conditional Import
```jinja2
{% if async %}
from fastmcp import Context
{% endif %}
```

### Iterating Parameters
```jinja2
{% for param in params %}
{{ param.name }}: Annotated[{{ param.type }}, "{{ param.description }}"]{% if not param.required %} = {{ param.default }}{% endif %},
{% endfor %}
```

### Conditional Decorator
```jinja2
{% if with_auth %}
@requires_scopes("read:data")
{% endif %}
@mcp.tool()
```

## Best Practices

1. **Keep templates simple** - Complex logic should be in the CLI, not templates
2. **Include TODO comments** - Guide developers to implement business logic
3. **Provide examples** - Show common patterns in comments
4. **Test generated code** - Ensure templates produce valid, working Python
5. **Document variables** - Update README when adding new variables

## Sharing Templates

Templates can be:
- **Versioned with your project** - Committed to git
- **Shared across projects** - Copy to other projects
- **Published as templates** - Fork and customize for your organization

## See Also

- [GENERATOR_PLAN.md](../GENERATOR_PLAN.md) - Comprehensive generator system documentation
- [ARCHITECTURE.md](../ARCHITECTURE.md) - Project architecture overview
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Contributing guidelines
