"""Builds the system prompt and message contents for Gemini.

The companion prompt is a version-controlled text file; this module injects the
active conversation mode and trims history to a bounded size.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.schemas import MODES, Mode

PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "companion_system_prompt.txt"

DEFAULT_COMPANION_NAME = "Friendly Companion"

_MODE_DIRECTIVES: dict[str, str] = {
    "friendly": "MODE: friendly (default). Talk like a comfortable, trusted friend.",
    "respectful": (
        "MODE: respectful. Use polite, dignified language and respectful address "
        "(for example 'sir' / 'ungalukku'). No teasing or slang. Return to normal "
        "friendly Tanglish as soon as the user asks."
    ),
    "playful": (
        "MODE: playful / light roast. Affectionate, mild teasing is welcome when the "
        "situation supports it. Never mock appearance, identity, disability, background "
        "or vulnerabilities, and stop immediately if the user is uncomfortable."
    ),
    "supportive": (
        "MODE: supportive. The user seems to need encouragement. Be patient, kind and "
        "helpful; reduce jokes."
    ),
    "focused": (
        "MODE: focused / professional. Be precise and efficient. Minimal humor, clear "
        "structure, answer the actual question."
    ),
}


class PromptService:
    def __init__(self, prompt_file: Path | None = None) -> None:
        self.prompt_file = prompt_file or PROMPT_FILE
        self._base = self._load()

    def _load(self) -> str:
        try:
            text = self.prompt_file.read_text(encoding="utf-8")
        except OSError:
            # Fallback keeps the app usable if the file is missing.
            text = (
                "You are {name}, a friendly personal AI companion. Reply in natural "
                "Romanized Tanglish or English, never Tamil script by default."
            )
        return text.strip()

    @property
    def base_prompt(self) -> str:
        return self._base

    def reload(self) -> str:
        self._base = self._load()
        return self._base

    @staticmethod
    def apply_name(prompt: str, name: str | None) -> str:
        """Substitute the companion's name into the prompt template.

        The name comes from the user, so it is escaped before it reaches the
        model: a name containing braces or a newline must never be able to
        alter the rest of the prompt.
        """
        safe = (name or "").strip() or DEFAULT_COMPANION_NAME
        safe = safe.replace("{", "(").replace("}", ")")
        safe = " ".join(safe.split())[:40]
        return prompt.replace("{name}", safe)

    def system_prompt(
        self, mode: Mode | str | None = None, name: str | None = None
    ) -> str:
        directive = _MODE_DIRECTIVES.get(mode or "friendly", _MODE_DIRECTIVES["friendly"])
        prompt = self.apply_name(self._base, name)
        return f"{prompt}\n\nCURRENT CONVERSATION MODE\n{directive}"

    def valid_modes(self) -> tuple[str, ...]:
        return MODES

    def build_contents(
        self,
        history: list[dict[str, Any]],
        new_message: str,
        attachment_parts: list[Any] | None = None,
        limit: int = 40,
    ) -> list[Any]:
        """Conversation history plus the new user turn, trimmed to `limit` turns.

        `history` items look like {"role": "user"|"assistant", "content": str}.
        Returns SDK `types.Part`-friendly dicts; attachments are prepended to the
        final user turn so the model sees them with the question.
        """
        trimmed = [h for h in history if h.get("content")][-max(0, limit - 1) :]
        contents: list[Any] = [
            {"role": self.to_model_role(str(item["role"])), "parts": [{"text": str(item["content"])}]}
            for item in trimmed
            if item.get("role") in {"user", "assistant", "model"}
        ]

        parts: list[Any] = []
        if attachment_parts:
            parts.extend(attachment_parts)
        parts.append({"text": new_message})
        # Gemini uses role "model" for assistant turns.
        contents.append({"role": "user", "parts": parts})
        return contents

    @staticmethod
    def to_model_role(role: str) -> str:
        return "model" if role == "assistant" else "user"
