"""Parse long-text paste with a single trailing MCP footer line."""

import re
from typing import Literal, Tuple

PasteTarget = Literal["partner", "opportunity"]


def parse_paste_footer(full_text: str) -> Tuple[str, PasteTarget]:
    """
    Split body vs directive using the last non-empty line.
    Accepted footers (case-insensitive; flexible whitespace after '+'):
      + add to partner
      + add to opportunity
    """
    if not full_text or not str(full_text).strip():
        raise ValueError("full_text is empty.")

    lines = str(full_text).replace("\r\n", "\n").split("\n")
    last_i = len(lines) - 1
    while last_i >= 0 and not lines[last_i].strip():
        last_i -= 1
    if last_i < 0:
        raise ValueError("full_text has no non-empty lines.")

    directive_line = lines[last_i].strip()
    m = re.match(r"^\s*\+\s*(.+)$", directive_line, re.IGNORECASE | re.DOTALL)
    if not m:
        raise ValueError(
            'Last non-empty line must be "+ add to partner" or "+ add to opportunity" '
            "(spacing after + is flexible, matching is case-insensitive)."
        )
    inner = re.sub(r"\s+", " ", m.group(1).strip().lower())
    if inner == "add to partner":
        target: PasteTarget = "partner"
    elif inner == "add to opportunity":
        target = "opportunity"
    else:
        raise ValueError(
            f'Unknown footer directive: {directive_line!r}. '
            'Use "+ add to partner" or "+ add to opportunity".'
        )

    body_lines = lines[:last_i]
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    body = "\n".join(body_lines).strip()
    if not body:
        raise ValueError("No note body above the footer line.")

    return body, target
