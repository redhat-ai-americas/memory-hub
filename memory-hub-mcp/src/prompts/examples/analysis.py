"""
Data analysis prompts for text processing and classification.

These prompts demonstrate FastMCP 2.x decorator-based prompt patterns with:
- Simplified Field() pattern for parameter validation
- Type hints with parameterized types (dict[str, str])
- Docstrings for documentation
- Optional parameters with defaults
- FastMCP 2.9.0+ compatibility
"""

from pydantic import Field

# Import the shared mcp instance from core
from ...core.app import mcp


@mcp.prompt
def summarize(
    document: str = Field(
        description="The document text to summarize",
        min_length=1,
    ),
) -> str:
    """
    Summarize a document with clear section markers.

    This prompt takes a document and requests a concise summary with key points.
    The response should be structured JSON with a summary field and key_points array.

    Args:
        document: The text content to be summarized

    Returns:
        A formatted prompt string requesting a structured summary
    """
    return f"""Summarize the following text:
<document>{document}</document>
Use clear, concise language.

Return your response as JSON with this structure:
{{
  "summary": "A concise summary of the main content",
  "key_points": ["Key point 1", "Key point 2", "Key point 3"]
}}"""


@mcp.prompt
def classify(
    text: str = Field(
        description="The text to classify into categories",
        min_length=1,
    ),
) -> str:
    """
    Classify text into categories with confidence scores.

    This prompt analyzes text and assigns it to appropriate categories
    along with confidence scores for the classification.

    Args:
        text: The text content to classify

    Returns:
        A formatted prompt string requesting structured classification results
    """
    return f"""Classify the following text:
<text>{text}</text>

Return JSON matching this schema:
{{
  "category": "The primary category for this text",
  "confidence": 0.95
}}"""


@mcp.prompt
def analyze_sentiment(
    text: str = Field(
        description="The text to analyze for sentiment",
        min_length=1,
    ),
) -> str:
    """
    Analyze the sentiment of given text (positive, negative, neutral).

    Args:
        text: The text content to analyze

    Returns:
        A formatted prompt string requesting sentiment analysis
    """
    return f"""Analyze the sentiment of the following text:
<text>{text}</text>

Provide:
1. Overall sentiment (positive, negative, or neutral)
2. Sentiment score (-1.0 to 1.0)
3. Key phrases that influenced the sentiment
4. Brief explanation of the analysis

Return as JSON:
{{
  "sentiment": "positive|negative|neutral",
  "score": 0.8,
  "key_phrases": ["phrase1", "phrase2"],
  "explanation": "Brief explanation"
}}"""


@mcp.prompt
def extract_entities(
    text: str = Field(
        description="The text to extract named entities from",
        min_length=1,
    ),
    entity_types: list[str] | None = Field(
        default=None,
        description=(
            "Specific entity types to extract "
            "(e.g., ['PERSON', 'ORGANIZATION', 'LOCATION'])"
        ),
    ),
) -> str:
    """
    Extract named entities from text with optional filtering by entity type.

    This example shows how to handle optional parameters in prompts.

    Args:
        text: The text content to analyze
        entity_types: Optional list of specific entity types to extract

    Returns:
        A formatted prompt string requesting entity extraction
    """
    entity_filter = ""
    if entity_types:
        types_str = ", ".join(entity_types)
        entity_filter = f"\nFocus on these entity types: {types_str}"

    return f"""Extract named entities from the following text:
<text>{text}</text>{entity_filter}

Return JSON with entities grouped by type:
{{
  "PERSON": ["John Doe", "Jane Smith"],
  "ORGANIZATION": ["ACME Corp", "Tech Inc"],
  "LOCATION": ["New York", "San Francisco"],
  "DATE": ["2024-01-01"],
  "OTHER": ["Any other relevant entities"]
}}"""


@mcp.prompt
def analyze_data(
    data: dict[str, str] = Field(
        description=(
            "Data to analyze as a dictionary with string keys and values. "
            "Pass as JSON string."
        )
    ),
    analysis_type: str = Field(
        default="summary",
        description="Type of analysis: 'summary', 'detailed', or 'statistical'",
    ),
) -> str:
    """
    Analyze structured data and provide insights.

    This example demonstrates FastMCP 2.9.0+ dict parameter handling.
    Clients pass dict as JSON string, FastMCP converts automatically.

    Args:
        data: Dictionary of data to analyze
        analysis_type: Type of analysis to perform

    Returns:
        Formatted prompt for data analysis
    """
    return f"""Analyze the following data:

{data}

Perform a {analysis_type} analysis including:
1. Key patterns and trends
2. Notable outliers or anomalies
3. Statistical summaries (if applicable)
4. Actionable insights

Return results as structured JSON."""
