"""
General utility prompts for common tasks.

These prompts provide general-purpose functionality that doesn't fit
into more specific categories.
"""

from typing import Annotated, Literal
from pydantic import Field

from ...core.app import mcp


@mcp.prompt()
def translate_text(
    text: Annotated[
        str,
        Field(description="The text to translate"),
    ],
    target_language: Annotated[
        str,
        Field(description="Target language (e.g., 'Spanish', 'French', 'German')"),
    ],
    source_language: Annotated[
        str | None,
        Field(
            description="Source language (auto-detect if not specified)", default=None
        ),
    ] = None,
) -> str:
    """
    Translate text from one language to another.

    Args:
        text: The text to translate
        target_language: The language to translate to
        source_language: Optional source language (auto-detected if not provided)

    Returns:
        A formatted prompt for text translation
    """
    source_info = ""
    if source_language:
        source_info = f"Source language: {source_language}\n"

    return f"""Translate the following text to {target_language}:

{source_info}<text>{text}</text>

Provide:
1. The translated text
2. Any cultural or contextual notes that might be relevant
3. Alternative translations if applicable

Return as JSON:
{{
  "translation": "The translated text",
  "notes": "Any relevant context or notes",
  "alternatives": ["alternative1", "alternative2"]
}}"""


@mcp.prompt()
def proofread_text(
    text: Annotated[
        str,
        Field(description="The text to proofread"),
    ],
    style: Annotated[
        Literal["formal", "casual", "technical", "creative"],
        Field(description="Writing style context"),
    ] = "formal",
) -> str:
    """
    Proofread and improve text for grammar, clarity, and style.

    Args:
        text: The text to proofread
        style: The intended writing style

    Returns:
        A formatted prompt string for proofreading
    """
    style_guidance = {
        "formal": "professional and academic contexts, maintain formal tone",
        "casual": "conversational contexts, maintain approachable tone",
        "technical": "technical documentation, prioritize precision and clarity",
        "creative": "creative writing, enhance style while preserving voice",
    }

    guidance = style_guidance.get(style, style_guidance["formal"])

    return f"""Proofread and improve the following text:

<text>{text}</text>

Context: This text is for {guidance}.

Provide:
1. Corrected version of the text
2. List of specific corrections made (grammar, spelling, punctuation)
3. Style suggestions for improvement
4. Overall feedback on clarity and effectiveness

Return as JSON:
{{
  "corrected_text": "The improved version",
  "corrections": [
    {{"type": "grammar", "original": "...", "corrected": "...", "explanation": "..."}},
    {{"type": "style", "original": "...", "suggested": "...", "reason": "..."}}
  ],
  "overall_feedback": "General comments on the text"
}}"""


@mcp.prompt()
def compare_texts(
    text1: Annotated[
        str,
        Field(description="First text to compare"),
    ],
    text2: Annotated[
        str,
        Field(description="Second text to compare"),
    ],
    comparison_type: Annotated[
        Literal["similarity", "differences", "both"],
        Field(description="What to focus on in the comparison"),
    ] = "both",
) -> str:
    """
    Compare two texts and identify similarities and/or differences.

    Args:
        text1: First text
        text2: Second text
        comparison_type: Focus on similarities, differences, or both

    Returns:
        A formatted prompt for text comparison
    """
    focus_instruction = {
        "similarity": "Focus on identifying similarities and common themes.",
        "differences": "Focus on identifying differences and contrasts.",
        "both": "Identify both similarities and differences.",
    }

    focus = focus_instruction.get(comparison_type, focus_instruction["both"])

    return f"""Compare the following two texts:

<text1>
{text1}
</text1>

<text2>
{text2}
</text2>

{focus}

Provide:
1. Key similarities (if applicable)
2. Key differences (if applicable)
3. Tone and style comparison
4. Content and meaning analysis
5. Overall assessment

Return as JSON:
{{
  "similarities": ["similarity1", "similarity2"],
  "differences": ["difference1", "difference2"],
  "tone_analysis": "Comparison of tone and style",
  "content_analysis": "Comparison of content and meaning",
  "summary": "Overall assessment"
}}"""


@mcp.prompt()
def generate_title(
    content: Annotated[
        str,
        Field(description="The content to generate a title for"),
    ],
    num_options: Annotated[
        int,
        Field(description="Number of title options to generate", ge=1, le=10),
    ] = 3,
) -> str:
    """
    Generate engaging titles for given content.

    Args:
        content: The content that needs a title
        num_options: Number of title variations to generate (1-10)

    Returns:
        A formatted prompt for title generation
    """
    return f"""Generate {num_options} compelling title options for the following content:

<content>
{content}
</content>

Each title should:
1. Accurately represent the content
2. Be engaging and attention-grabbing
3. Be concise (ideally under 10 words)
4. Be unique from the other options

Return as JSON:
{{
  "titles": [
    {{"title": "Title Option 1", "style": "descriptive|creative|professional", "rationale": "Why this works"}},
    {{"title": "Title Option 2", "style": "descriptive|creative|professional", "rationale": "Why this works"}}
  ],
  "recommendation": "Which title works best and why"
}}"""
