# Add Skill

Add a new skill directory following the agentskills.io specification. Skills are capabilities that are too large to keep in context all the time — they load on demand via progressive disclosure.

**Prerequisite: `/create-agent` must have been run first.** Verify `src/agent.py` exists and contains a BaseAgent subclass before proceeding.

**Before adding a skill, consider whether a tool or prompt would be simpler.** Skills are for capabilities that have their own instructions, scripts, or reference material. If the capability is just a function call, use `/add-tool`. If it is just a prompt template, add a file to `prompts/`.

## Process

### Step 1: Understand the Skill

Ask the developer:

1. **What does the skill do?** Get a one-paragraph description of the capability.
2. **When should it activate?** What user inputs or conditions should trigger this skill? These become the trigger words in the SKILL.md frontmatter.
3. **What parameters does it accept?** Name, type, default value, and description for each.
4. **Does it need supporting files?** Scripts (e.g., a Python helper), reference material (e.g., an API spec), or assets (e.g., template files) that the skill depends on.
5. **What dependencies does it have?** Other skills, tools, or external services it requires.

### Step 2: Choose a Name

The skill name should be:
- Lowercase with hyphens (e.g., `code-review`, `data-analysis`, `report-generation`)
- Descriptive enough that another developer can guess what it does from the name
- Unique among existing skills. Check what exists:
  ```bash
  ls -d skills/*/
  ```

### Step 3: Create the Skill Directory

Create the skill directory structure:

```
skills/<skill-name>/
  SKILL.md
```

Add optional subdirectories only if the skill needs them:

```
skills/<skill-name>/
  SKILL.md
  scripts/       # Helper scripts the skill references
  references/    # Documentation, API specs, schemas
  assets/        # Templates, sample data, images
```

Do not create empty subdirectories. Only create what the skill actually uses.

### Step 4: Write SKILL.md

The SKILL.md file has YAML frontmatter and a Markdown body.

**Frontmatter** (required fields):

```yaml
---
name: skill-name
description: One-sentence description of what the skill does
version: "1.0"
triggers:
  - trigger-word-1
  - trigger-word-2
dependencies: []
parameters:
  param_name:
    type: string
    default: "default value"
    description: What this parameter controls
---
```

- `triggers` should be words or short phrases that, when present in user input, suggest this skill is relevant. Keep them specific — overly broad triggers cause false activations.
- `dependencies` lists other skills this skill requires. Leave empty (`[]`) for standalone skills.
- `parameters` configure the skill's behavior. Each parameter needs a type, default, and description.

**Body** (the full skill instructions, loaded when the skill activates):

Write the body as clear, actionable instructions that tell the agent what to do when this skill is active. Include:

1. **Behavior**: Step-by-step instructions for the skill's workflow.
2. **Output format**: What the output should look like (Markdown structure, data format, etc.).
3. **Constraints**: What the skill should not do or assumptions it should not make.
4. **Example**: At least one concrete example showing input and expected output.

The body is what gets loaded into context when `load_skill(name)` is called. It should be self-contained — an agent reading only the body should understand what to do.

Keep the body under 500 tokens if possible. Skills that are too large defeat the purpose of progressive disclosure. If the instructions are genuinely long, consider breaking the skill into multiple smaller skills.

### Step 5: Add Supporting Files (if needed)

If the skill needs scripts, references, or assets:

- **Scripts** (`scripts/`): Executable helpers the skill references. Include a shebang line and make them executable. The agent can invoke them via a tool or subprocess.
- **References** (`references/`): Read-only material the skill needs for context — API specs, schemas, documentation excerpts. Loaded on demand, not at startup.
- **Assets** (`assets/`): Templates, sample data, or other static files the skill operates on.

All supporting files should be referenced from the SKILL.md body so the agent knows they exist and when to load them.

### Step 6: Verify the Skill Loads

Confirm the skill is discovered by the SkillLoader:

```bash
python -c "
from fipsagents.baseagent.skills import SkillLoader
loader = SkillLoader()
stubs = loader.load_all('./skills')
for s in stubs:
    print(f'  {s.name}: {s.description}')
    print(f'    triggers: {s.triggers}')
"
```

The new skill should appear with the correct name, description, and triggers.

If it does not appear:
- Verify the directory is directly under `skills/` (not nested deeper)
- Verify `SKILL.md` exists in the skill directory (exact filename, capitalized)
- Check for YAML parsing errors in the frontmatter

### Step 7: Update the System Prompt (optional)

If the skill should be mentioned in the system prompt so the LLM knows it is available, update `prompts/system.md`. BaseAgent's `build_system_prompt()` automatically appends a skill manifest (name, description, triggers), but you may want to add specific guidance on when to activate the skill.

### Step 8: Run Tests

Run `make test` to verify nothing is broken. Skills are loaded at startup, so a malformed SKILL.md can break agent initialization.

### Step 9: Summary

Tell the developer:
- Skill name and directory location
- Trigger words
- Parameters and their defaults
- Whether supporting files were created
- Whether the system prompt was updated
