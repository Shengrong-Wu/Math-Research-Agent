from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ContextPressure:
    """Current context window pressure level."""
    used_tokens: int
    max_tokens: int
    level: str  # "low" | "moderate" | "high" | "critical"

    @property
    def ratio(self) -> float:
        if self.max_tokens == 0:
            return 0.0
        return self.used_tokens / self.max_tokens

class TokenBudget:
    """Track token usage and detect context pressure."""

    def __init__(self, max_tokens: int = 200_000):
        self.max_tokens = max_tokens
        self._used_tokens = 0
        self._turn_history: list[int] = []  # tokens per turn

    def update(self, tokens_used: int) -> None:
        """Record tokens used in the latest turn."""
        self._used_tokens = tokens_used
        self._turn_history.append(tokens_used)

    def pressure(self) -> ContextPressure:
        """Get current pressure level."""
        ratio = self._used_tokens / self.max_tokens if self.max_tokens else 0
        if ratio > 0.95:
            level = "critical"
        elif ratio > 0.85:
            level = "high"
        elif ratio > 0.60:
            level = "moderate"
        else:
            level = "low"
        return ContextPressure(
            used_tokens=self._used_tokens,
            max_tokens=self.max_tokens,
            level=level,
        )

    def recent_delta(self, window: int = 3) -> int:
        """Average tokens added per turn over the last `window` turns."""
        if len(self._turn_history) < 2:
            return 0
        recent = self._turn_history[-window:]
        if len(recent) < 2:
            return 0
        return (recent[-1] - recent[0]) // max(len(recent) - 1, 1)

    def turns_until_critical(self) -> int | None:
        """Estimate how many turns until context is critical."""
        delta = self.recent_delta()
        if delta <= 0:
            return None
        remaining = int(self.max_tokens * 0.95) - self._used_tokens
        if remaining <= 0:
            return 0
        return remaining // delta
