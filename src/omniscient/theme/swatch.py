"""Terminal swatches for `omniscient theme list` / `theme export` (pure rich, no TUI)."""

from __future__ import annotations

from rich.text import Text

from omniscient.theme.palettes import SEMANTIC_SLOTS, Palette

SWATCH = "██"


def swatch(palette: Palette, slots: tuple[str, ...] = SEMANTIC_SLOTS) -> Text:
    out = Text()
    for slot in slots:
        out.append(SWATCH, style=palette.colors()[slot])
    return out


def ansi_strip(palette: Palette) -> Text:
    """The 16 ANSI colours as two rows of blocks (normal, bright)."""
    out = Text()
    for row in (palette.ansi[:8], palette.ansi[8:]):
        for color in row:
            out.append("   ", style=f"on {color}")
        out.append("\n")
    out.rstrip()
    return out
