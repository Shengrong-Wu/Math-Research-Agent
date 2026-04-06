from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ProgressEntry:
    """Record of a single iteration's progress."""
    iteration: int
    steps_proved: int  # total steps proved so far
    new_insights: bool  # did MEMO get meaningful new content?
    step_status_changed: bool  # did any step status change?

class DiminishingReturnsDetector:
    """Detect when the agent is making no progress and should abandon the roadmap.

    Triggers when the last K iterations produced no new proved steps and
    no meaningful new insights.
    """

    def __init__(self, window: int = 3):
        self.window = window
        self._history: list[ProgressEntry] = []

    def record(self, entry: ProgressEntry) -> None:
        """Record progress for the current iteration."""
        self._history.append(entry)

    def should_abandon(self) -> bool:
        """Check if the roadmap should be abandoned due to no progress."""
        if len(self._history) < self.window:
            return False

        recent = self._history[-self.window:]

        # Check if any step status changed in the window
        any_status_change = any(e.step_status_changed for e in recent)

        # Check if steps_proved increased
        proved_start = recent[0].steps_proved
        proved_end = recent[-1].steps_proved
        proved_increased = proved_end > proved_start

        # Check if any new insights
        any_insights = any(e.new_insights for e in recent)

        # Abandon if none of these happened
        return not any_status_change and not proved_increased and not any_insights

    def progress_summary(self) -> str:
        """Human-readable progress summary."""
        if not self._history:
            return "No iterations recorded."

        latest = self._history[-1]
        total = len(self._history)
        proved = latest.steps_proved

        if self.should_abandon():
            return (
                f"Iteration {total}: {proved} steps proved. "
                f"No progress in last {self.window} iterations. "
                f"Recommend: abandon roadmap."
            )
        return f"Iteration {total}: {proved} steps proved. Making progress."

    def reset(self) -> None:
        """Reset history for a new roadmap."""
        self._history.clear()
