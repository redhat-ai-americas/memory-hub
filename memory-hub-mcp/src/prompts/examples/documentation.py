"""
Documentation generation prompts.

These prompts help generate various types of documentation including
API docs, code comments, README files, and technical documentation.
"""

from typing import Annotated
from pydantic import Field

from ...core.app import mcp


@mcp.prompt()
def generate_docstring(
    code: Annotated[
        str,
        Field(
            description="The code (function, class, or module) to document",
            min_length=1,
        ),
    ],
    style: Annotated[
        str,
        Field(
            description="Documentation style (google, numpy, sphinx)",
            default="google",
        ),
    ] = "google",
) -> str:
    """
    Generate a docstring for given code following specified style guide.

    Args:
        code: The code to document
        style: Docstring style format (google, numpy, or sphinx)

    Returns:
        A formatted prompt requesting appropriate docstring generation
    """
    return f"""Generate a comprehensive docstring for the following code:

<code>
{code}
</code>

Use {style} style docstring format.

Include:
1. Brief one-line summary
2. Detailed description (if needed)
3. Args/Parameters with types and descriptions
4. Returns with type and description
5. Raises (if applicable)
6. Examples (if helpful)

Return only the docstring text, properly formatted."""


@mcp.prompt()
def generate_readme(
    project_name: Annotated[
        str,
        Field(description="Name of the project"),
    ],
    description: Annotated[
        str,
        Field(description="Brief description of what the project does"),
    ],
    features: Annotated[
        list[str] | None,
        Field(description="List of key features", default=None),
    ] = None,
) -> str:
    """
    Generate a comprehensive README.md for a project.

    Args:
        project_name: The name of the project
        description: Short description of the project
        features: Optional list of key features to highlight

    Returns:
        A formatted prompt string for README generation
    """
    features_section = ""
    if features:
        features_list = "\n".join(f"- {f}" for f in features)
        features_section = f"\n\nKey features:\n{features_list}"

    return f"""You are a technical documentation expert. Generate clear,
comprehensive, and well-structured README files following best practices.

Create a complete README.md for the following project:

Project Name: {project_name}
Description: {description}{features_section}

The README should include:
1. Project title and badges (if applicable)
2. Brief description
3. Features (if provided)
4. Installation instructions
5. Usage examples
6. Configuration (if applicable)
7. Contributing guidelines
8. License information
9. Contact/Support information

Use markdown formatting and make it professional yet approachable."""


@mcp.prompt()
def explain_code(
    code: Annotated[
        str,
        Field(description="The code to explain"),
    ],
    audience: Annotated[
        str,
        Field(
            description="Target audience (beginner, intermediate, expert)",
            default="intermediate",
        ),
    ] = "intermediate",
) -> str:
    """
    Explain what a piece of code does in plain language.

    Adjusts explanation complexity based on the target audience.

    Args:
        code: The code to explain
        audience: The technical level of the audience

    Returns:
        A formatted prompt string for code explanation
    """
    audience_guidance = {
        "beginner": "Use simple language, avoid jargon, explain basic concepts.",
        "intermediate": "Assume familiarity with programming concepts, focus on logic and patterns.",
        "expert": "Focus on algorithms, optimizations, edge cases, and design patterns.",
    }

    guidance = audience_guidance.get(audience, audience_guidance["intermediate"])

    return f"""Explain what the following code does:

<code>
{code}
</code>

Target audience: {audience}
{guidance}

Provide:
1. High-level overview of what the code does
2. Step-by-step explanation of the logic
3. Key concepts or patterns used
4. Potential issues or edge cases
5. Suggestions for improvement (if any)"""


@mcp.prompt()
def generate_api_docs(
    endpoint_code: Annotated[
        str,
        Field(description="The API endpoint code to document"),
    ],
    include_examples: Annotated[
        bool,
        Field(description="Include request/response examples", default=True),
    ] = True,
) -> str:
    """
    Generate API documentation for an endpoint.

    Args:
        endpoint_code: The API endpoint code
        include_examples: Whether to include curl and response examples

    Returns:
        A formatted prompt for API documentation generation
    """
    examples_instruction = ""
    if include_examples:
        examples_instruction = """
Include practical examples:
- curl command examples
- Example request body (if applicable)
- Example successful response
- Example error responses"""

    return f"""Generate comprehensive API documentation for the following endpoint:

<code>
{endpoint_code}
</code>

Documentation should include:
1. Endpoint path and HTTP method
2. Description of what the endpoint does
3. Authentication requirements (if any)
4. Request parameters (path, query, body)
5. Request headers
6. Response format and status codes
7. Error responses{examples_instruction}

Format as markdown suitable for API documentation."""
