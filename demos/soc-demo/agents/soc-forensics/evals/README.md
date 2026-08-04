# Evals

Lightweight, harness-agnostic evaluation framework for agents built with
BaseAgent. Eval cases live alongside agent code and go through the same
review process as any other source change.

## Quick start

```bash
# List available eval cases
python -m evals.run_evals --dry-run

# Run all cases with mock LLM (no live endpoint needed)
python -m evals.run_evals

# Run a single case
python -m evals.run_evals --case basic_happy_path

# Run cases matching a tag
python -m evals.run_evals --tag smoke

# Run against a real LLM endpoint
python -m evals.run_evals --real-llm
```

Or via Makefile (when an `eval` target is added):

```bash
make eval
```

## Writing eval cases

Eval cases are defined in `evals.yaml`. Each case has:

| Field               | Required | Description |
|---------------------|----------|-------------|
| `name`              | yes      | Unique identifier, used with `--case` |
| `description`       | yes      | What this eval is testing and why |
| `input`             | yes      | The user query sent to the agent |
| `expected_behavior` | no       | Prose description (not machine-checked) |
| `tags`              | no       | List of strings for filtering (`--tag`) |
| `assertions`        | yes      | List of machine-checked assertions |

Example:

```yaml
cases:
  - name: my_eval_case
    description: Verify the agent produces a useful response for a typical query.
    input: "Example user query for your agent"
    expected_behavior: >
      The agent should call its primary tool and produce a structured
      response with the expected fields populated.
    tags: [smoke]
    assertions:
      - type: field_exists
        field: answer
      - type: contains
        field: answer
        value: expected-keyword
      - type: field_gte
        field: confidence
        value: 0.6
      - type: tool_called
        tool: example_tool
```

## Assertion types

Each assertion has a `type` and type-specific parameters.

### `field_exists`

Checks that a field on the agent's output object is present and not None.

```yaml
- type: field_exists
  field: answer
```

### `contains`

Case-insensitive substring check on a field's string value.

```yaml
- type: contains
  field: answer
  value: expected-keyword
```

### `not_contains`

Inverse of `contains` -- fails if the substring is found.

```yaml
- type: not_contains
  field: answer
  value: hallucinated
```

### `field_gte`

Checks that a numeric field is greater than or equal to a threshold.

```yaml
- type: field_gte
  field: confidence
  value: 0.7
```

### `field_lte`

Checks that a numeric field is less than or equal to a threshold.

```yaml
- type: field_lte
  field: confidence
  value: 0.9
```

### `tool_called`

Checks that a specific tool was invoked during the eval. Optional
`min_calls` parameter (defaults to 1).

```yaml
- type: tool_called
  tool: example_tool
  min_calls: 2
```

### `custom`

Placeholder for assertions that require custom logic. The built-in runner
skips these; external harnesses can register their own handlers.

```yaml
- type: custom
  fn: my_module.check_citation_format
```

## Fixtures

The `fixtures/` directory holds JSON files with sample data (e.g. mock
search results) that eval cases or custom assertion functions can load.
The runner provides a `load_fixture(name)` helper:

```python
from evals.run_evals import load_fixture

data = load_fixture("sample_search_results.json")
```

## How the mock LLM works

By default the runner replaces the agent's LLM client with mocks so evals
run without a live model endpoint. `evals/discovery.py` walks the agent
module to find the agent class, an LLM-visible tool name, and any
Pydantic output model — the mock factory then produces:

1. A first `call_model` response containing a tool call against the
   discovered LLM-visible tool (skipped when no LLM tools are
   registered, in which case the runner returns text directly).
2. A second `call_model` response with text content (no tool calls).
3. A `call_model_json` response returning a mock instance of the
   discovered Pydantic output model (skipped when the agent does not
   define one).
4. A `call_model_validated` response that passes validation.

To run against a real LLM, pass `--real-llm`. This requires a configured
model endpoint in `agent.yaml` or the appropriate environment variables.

## Integrating external eval harnesses

The YAML format is intentionally simple so external tools can consume it:

- **Promptfoo**: Write a small adapter that reads `evals.yaml` and maps
  cases to Promptfoo test configs.
- **Braintrust**: Use the YAML cases as inputs to Braintrust experiments,
  mapping assertions to Braintrust scorers.
- **Custom harness**: Load `evals.yaml` with any YAML parser. The
  `run_evals.py` module exports `load_eval_cases()`, `check_assertion()`,
  and `load_fixture()` for reuse.

The built-in runner is a starting point, not a ceiling. Replace or extend
it as your eval needs grow.

## Adding custom assertion functions

For assertions that go beyond field checks (e.g. semantic similarity,
regex matching, calling an LLM-as-judge), write a Python function and
register it with an external harness. The `custom` assertion type is
reserved for this pattern.

A typical approach:

1. Create a module (e.g. `evals/custom_checks.py`) with functions that
   accept the agent output and return `(passed: bool, detail: str)`.
2. In your external harness config, map `custom` assertions to those
   functions.
3. The built-in runner will skip `custom` assertions with a note; your
   harness handles them.
