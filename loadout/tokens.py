"""Token-size check and the Hub & Spoke refactoring prompt."""
from .config import CHARS_PER_TOKEN, TOKEN_LIMIT_CHARS

WARNING_TITLE = "High Token Consumption Detected"
WARNING_TEXT = (
    "This skill exceeds 12,000 characters. We recommend modularizing it into a "
    "Hub & Spoke architecture (SKILL.md orchestrator + /modules/ sub-skills)."
)

HUB_SPOKE_PROMPT = """You are an expert in prompt architecture and Context Window optimization for AI Agents.

Your task is to refactor the Markdown file provided below, which has exceeded the recommended token size, and split it into a modular structure following the Hub & Spoke (Progressive Disclosure) design pattern.

---

### 1. Output Guidelines
Generate the content of the files organized in the following directory structure:

.[skill-name]/
├── SKILL.md              
├── modules/              
│   ├── 01-[step-1].md
│   ├── 02-[step-2].md
│   └── ...
└── scripts/              

---

### 2. Refactoring Rules

1. **The Main File (`SKILL.md`):**
   - Must act ONLY as an orchestrator / decision tree.
   - Must contain a clear description of WHEN and HOW to use the skill.
   - Must include an explicit "On-Demand Reading" rule: strictly forbid the agent from loading all modules at once, and instruct it to read only the `.md` file corresponding to the current step.
   - Must outline the step-by-step flow, pointing to the relative file paths inside the `modules/` directory.

2. **The Modules (`modules/*.md`):**
   - Each file must contain a maximum of 150 lines and 5,000 characters, strictly focused on a single responsibility.
   - Must be fully self-contained within the context of that specific step.
"""


def exceeds_limit(text: str) -> bool:
    return len(text) > TOKEN_LIMIT_CHARS


def build_prompt(content: str | None = None) -> str:
    if not content:
        return HUB_SPOKE_PROMPT
    return f"{HUB_SPOKE_PROMPT}\n---\n\n### 3. File to Refactor\n\n```markdown\n{content}\n```\n"


def estimate(chars: int) -> int:
    """Rough token count from a character count."""
    return -(-chars // CHARS_PER_TOKEN)


def fmt(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
