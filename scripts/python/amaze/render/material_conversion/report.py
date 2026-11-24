"""What one conversion did, for an honest summary rather than a bare pass or fail."""

from amaze import messages
from amaze.core import renderers


def summary(made: int, total: int, sources, target: str) -> str:
    """The one message after a batch: `made` of `total` materials of `sources` became `target`."""
    shown = " and ".join(renderers.label(each.key) for each in renderers.ALL if each.key in sources)
    return messages.CONVERSION_SUMMARY % (made, total, shown, target)


class ConversionReport:
    """One conversion's skipped and approximated inputs, said instead of guessed."""

    def __init__(self, mat_name: str) -> None:
        self.mat_name = mat_name
        self.skipped: list[str] = []
        self.approximated: list[str] = []

    def skip(self, msg: str) -> None:
        self.skipped.append(msg)

    def approximate(self, msg: str) -> None:
        self.approximated.append(msg)

    def is_clean(self) -> bool:
        return not self.skipped and not self.approximated

    def summary_lines(self) -> list[str]:
        lines = [f'"{self.mat_name}":']
        for msg in self.approximated:
            lines.append("  [approximated] " + msg)
        for msg in self.skipped:
            lines.append("  [skipped] " + msg)
        if self.is_clean():
            lines.append("  fully converted, no skipped inputs")
        return lines
