"""Terminal output uses the desktop's default foreground for readable contrast."""

from rich.console import Console


# Disable ANSI styles, including dim text and automatic JSON highlighting.
console = Console(color_system=None, highlight=False)
