from dataclasses import dataclass


@dataclass(frozen=True)
class Hunk:
    """Hunk of difference in unified format.

    https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html
    """

    left_start: int
    left_count: int
    right_start: int
    right_count: int
