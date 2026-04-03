import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.app import mcp
from prompts.examples import analysis, documentation, general


def test_python_prompt_modules_loaded():
    """Test that Python prompt modules are properly imported."""
    # Verify modules exist
    assert analysis is not None
    assert documentation is not None
    assert general is not None


def test_analysis_prompt_functions_exist():
    """Test that analysis prompt functions exist and are wrapped by FastMCP."""
    # The decorator wraps functions into FunctionPrompt objects
    # Verify they exist as module attributes
    assert hasattr(analysis, "summarize")
    assert hasattr(analysis, "classify")
    assert hasattr(analysis, "analyze_sentiment")
    assert hasattr(analysis, "extract_entities")


def test_documentation_prompt_functions_exist():
    """Test that documentation prompt functions exist and are wrapped by FastMCP."""
    assert hasattr(documentation, "generate_docstring")
    assert hasattr(documentation, "generate_readme")
    assert hasattr(documentation, "explain_code")
    assert hasattr(documentation, "generate_api_docs")


def test_general_prompt_functions_exist():
    """Test that general utility prompt functions exist and are wrapped by FastMCP."""
    assert hasattr(general, "translate_text")
    assert hasattr(general, "proofread_text")
    assert hasattr(general, "compare_texts")
    assert hasattr(general, "generate_title")


def test_prompt_function_has_metadata():
    """Test that decorated prompt functions have proper metadata."""
    from fastmcp.prompts.prompt import FunctionPrompt

    # Check that the decorator created a FunctionPrompt object
    summarize_prompt = analysis.summarize
    assert isinstance(summarize_prompt, FunctionPrompt)

    # Verify it has name and description
    assert hasattr(summarize_prompt, "name")
    assert summarize_prompt.name == "summarize"

    # Verify it has the underlying function
    assert hasattr(summarize_prompt, "fn")
    assert callable(summarize_prompt.fn)


def test_prompt_underlying_function_callable():
    """Test that the underlying prompt function can be invoked."""
    from fastmcp.prompts.prompt import FunctionPrompt

    # Get the FunctionPrompt object
    summarize_prompt = analysis.summarize
    assert isinstance(summarize_prompt, FunctionPrompt)

    # Call the underlying function
    result = summarize_prompt.fn("Test document content")
    assert isinstance(result, str)
    assert "Test document content" in result
    assert "Summarize" in result or "summarize" in result


def test_prompt_with_optional_parameters_function():
    """Test prompts with optional parameters work at the function level."""
    from fastmcp.prompts.prompt import FunctionPrompt

    extract_prompt = analysis.extract_entities
    assert isinstance(extract_prompt, FunctionPrompt)

    # Test with no optional params
    result1 = extract_prompt.fn("John works at Google in New York")
    assert isinstance(result1, str)
    assert "John works at Google in New York" in result1

    # Test with optional entity_types
    result2 = extract_prompt.fn(
        "John works at Google in New York",
        entity_types=["PERSON", "ORGANIZATION"],
    )
    assert isinstance(result2, str)
    assert "PERSON" in result2
    assert "ORGANIZATION" in result2


def test_analyze_sentiment_prompt():
    """Test analyze_sentiment prompt returns proper string."""
    from fastmcp.prompts.prompt import FunctionPrompt

    sentiment_prompt = analysis.analyze_sentiment
    assert isinstance(sentiment_prompt, FunctionPrompt)

    result = sentiment_prompt.fn("This is great!")
    assert isinstance(result, str)
    assert "This is great!" in result
    assert "sentiment" in result.lower()


def test_generate_readme_prompt():
    """Test generate_readme prompt returns proper string."""
    from fastmcp.prompts.prompt import FunctionPrompt

    readme_prompt = documentation.generate_readme
    assert isinstance(readme_prompt, FunctionPrompt)

    result = readme_prompt.fn(
        "MyProject",
        "A test project",
        features=["Feature 1", "Feature 2"],
    )
    assert isinstance(result, str)
    assert "MyProject" in result
    assert "Feature 1" in result
    assert "Feature 2" in result


def test_prompt_parameter_validation():
    """Test that prompt functions accept parameters correctly."""
    from fastmcp.prompts.prompt import FunctionPrompt

    title_prompt = general.generate_title
    assert isinstance(title_prompt, FunctionPrompt)

    # Test with valid parameters
    result = title_prompt.fn("Some content", num_options=5)
    assert isinstance(result, str)
    assert "5" in result or "five" in result.lower()

    # Test with default parameters
    result = title_prompt.fn("Some content")
    assert isinstance(result, str)
    assert "3" in result or "three" in result.lower()


def test_prompts_have_docstrings():
    """Test that prompt functions have docstrings preserved."""
    from fastmcp.prompts.prompt import FunctionPrompt

    summarize_prompt = analysis.summarize
    assert isinstance(summarize_prompt, FunctionPrompt)

    # The underlying function should have a docstring
    assert summarize_prompt.fn.__doc__ is not None
    assert "Summarize" in summarize_prompt.fn.__doc__
