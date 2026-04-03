"""
Advanced examples showcasing FastMCP best practices and features.

This module demonstrates:
- Field validation with Pydantic
- Explicit error handling with ToolError
- Structured output with dataclasses
- Complex validation patterns
- Proper use of tool annotations
- Context usage patterns
"""

from typing import Annotated, Literal
from dataclasses import dataclass
from pydantic import Field
from fastmcp import Context
from fastmcp.exceptions import ToolError
from ...core.app import mcp


# Example 1: Field Validation
@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def process_data(
    count: Annotated[
        int, Field(description="Number of items to process", ge=1, le=100)
    ],
    name: Annotated[
        str, Field(description="Name for the operation", min_length=1, max_length=50)
    ],
    ctx: Context = None,
) -> str:
    """Process data with validation constraints.

    Demonstrates:
    - Pydantic Field validation for numeric ranges
    - String length constraints
    - Annotated descriptions for better API documentation
    """
    await ctx.info(f"Processing {count} items with name '{name}'")
    return f"Successfully processed {count} items named '{name}'"


# Example 2: Error Handling
@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def validate_input(
    data: Annotated[str, "Data to validate"],
    ctx: Context = None,
) -> str:
    """Example of explicit error handling with ToolError.

    Demonstrates:
    - Using ToolError for user-friendly error messages
    - Input validation patterns
    - Proper error context
    """
    await ctx.info("Validating input data")

    if not data.strip():
        raise ToolError("Data cannot be empty or whitespace")

    if len(data) > 1000:
        raise ToolError("Data exceeds maximum length of 1000 characters")

    # Check for potentially problematic characters
    if any(char in data for char in ["<", ">", "&"]):
        raise ToolError("Data contains potentially unsafe characters: <, >, or &")

    await ctx.info("Input validation successful")
    return f"Validated: {data[:50]}..." if len(data) > 50 else f"Validated: {data}"


# Example 3: Structured Output
@dataclass
class AnalysisResult:
    """Structured result for text analysis."""

    word_count: int
    character_count: int
    sentence_count: int
    avg_word_length: float
    unique_words: int


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def analyze_text(
    text: Annotated[str, "Text to analyze"],
    ctx: Context = None,
) -> AnalysisResult:
    """Analyze text and return structured results.

    Demonstrates:
    - Returning structured data using dataclasses
    - Complex data processing
    - Type-safe return values

    Returns:
        AnalysisResult: Structured analysis with multiple metrics
    """
    await ctx.info("Starting text analysis")

    if not text.strip():
        raise ToolError("Cannot analyze empty text")

    # Split into words (simple whitespace split)
    words = text.split()

    # Split into sentences (simple period split)
    sentences = [s.strip() for s in text.split(".") if s.strip()]

    # Calculate unique words
    unique_words = len(set(word.lower().strip(".,!?;:") for word in words))

    # Calculate average word length
    avg_length = sum(len(w) for w in words) / len(words) if words else 0.0

    result = AnalysisResult(
        word_count=len(words),
        character_count=len(text),
        sentence_count=len(sentences),
        avg_word_length=round(avg_length, 2),
        unique_words=unique_words,
    )

    await ctx.info(
        f"Analysis complete: {result.word_count} words, {result.sentence_count} sentences"
    )

    return result


# Example 4: Complex Validation with Literal Types
@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def configure_system(
    setting: Annotated[Literal["low", "medium", "high"], "Configuration level"],
    timeout: Annotated[int, Field(description="Timeout in seconds", ge=1, le=300)] = 30,
    verbose: Annotated[bool, "Enable verbose logging"] = False,
    ctx: Context = None,
) -> dict:
    """Configure system with validated parameters.

    Demonstrates:
    - Literal types for enum-like parameters
    - Multiple parameter types with defaults
    - Dictionary return type for flexible output
    - Combining multiple validation strategies
    """
    await ctx.info(f"Configuring system to {setting} with {timeout}s timeout")

    # Simulate configuration logic
    config = {
        "setting": setting,
        "timeout": timeout,
        "verbose": verbose,
        "status": "configured",
        "timestamp": "2025-10-10T00:00:00Z",  # In real code, use datetime
    }

    if verbose:
        await ctx.info(f"Verbose mode enabled. Full config: {config}")

    return config


# Example 5: List Processing with Validation
@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def calculate_statistics(
    numbers: Annotated[list[float], "List of numbers to analyze"],
    ctx: Context = None,
) -> dict:
    """Calculate statistics for a list of numbers.

    Demonstrates:
    - List parameter handling
    - Validation of collection contents
    - Statistical calculations
    - Comprehensive error checking
    """
    await ctx.info(f"Calculating statistics for {len(numbers)} numbers")

    if not numbers:
        raise ToolError("Cannot calculate statistics for empty list")

    if len(numbers) > 10000:
        raise ToolError("List too large (max 10000 numbers)")

    # Validate all numbers
    if not all(isinstance(n, (int, float)) for n in numbers):
        raise ToolError("All elements must be numbers")

    # Calculate statistics
    total = sum(numbers)
    mean = total / len(numbers)
    sorted_nums = sorted(numbers)

    # Calculate median
    n = len(sorted_nums)
    if n % 2 == 0:
        median = (sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2
    else:
        median = sorted_nums[n // 2]

    stats = {
        "count": len(numbers),
        "sum": round(total, 2),
        "mean": round(mean, 2),
        "median": round(median, 2),
        "min": min(numbers),
        "max": max(numbers),
        "range": round(max(numbers) - min(numbers), 2),
    }

    await ctx.info(
        f"Statistics calculated: mean={stats['mean']}, median={stats['median']}"
    )

    return stats


# Example 6: Optional Parameters with Smart Defaults
@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def format_text(
    text: Annotated[str, "Text to format"],
    uppercase: Annotated[bool, "Convert to uppercase"] = False,
    trim: Annotated[bool, "Trim whitespace"] = True,
    max_length: Annotated[
        int | None, Field(description="Maximum length (None for unlimited)", ge=1)
    ] = None,
    ctx: Context = None,
) -> str:
    """Format text with various options.

    Demonstrates:
    - Multiple optional parameters
    - Boolean flags
    - Optional (None-able) parameters
    - Conditional processing based on parameters
    """
    await ctx.info(
        f"Formatting text with options: uppercase={uppercase}, trim={trim}, max_length={max_length}"
    )

    result = text

    if trim:
        result = result.strip()

    if uppercase:
        result = result.upper()

    if max_length is not None and len(result) > max_length:
        result = result[:max_length] + "..."
        await ctx.info(f"Text truncated to {max_length} characters")

    return result
