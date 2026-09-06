"""Polvo ASCII banner — the artist octopus with his beret.

The octopus is a pixel-map conversion of the Polvo mascot
(icons8-polvo-96.png), hand-tuned into ASCII. The beret was added
with love (and manual pixel pushing). Rendered beside a figlet
'POLVO' wordmark to form the CLI welcome banner.
"""
from __future__ import annotations

from rich.console import Console
from rich.text import Text

# Pixel-map octopus, drawn with the same density ramp the pixel
# conversion produced (dense = @/#/S, light = : , .).
_OCTOPUS = [
    "                       @@@@@@@@",
    "                    ,@@@@@@@@@@@@@@,",
    "                    `@@@@@@@@@@@@@@'",
    "                    ..,::::,..",
    "                 ,+?S@@@@@@@@S?+,",
    "               :%@@@@@S%??%S@@@@@%:",
    "             .?@@@#*:..    ..:*#@@@?.",
    "            .S@@@*.            .*@@@S.",
    "           .?@@@+                +@@@?.",
    "           ,@@@S.                .S@@@,",
    ":?%+:.     ,@@@%   :?%+.  .+%?:   %@@@,     .:+?%:",
    "+@@@@S+.   ,@@@%.  +@@#.  .#@@+  .%@@@,   .+S@@@@+",
    ".:+%@@@*.  .S@@#.  .,:.    .:,.  .#@@S.  .*@@@%+:.",
    "   .%@@@,  .?@@@:                :@@@?.  ,@@@%.",
    "   .S@@@,   :@@@%.              .%@@@:   ,@@@S.",
    "  .%@@@+.    ?@@@;              ;@@@?    .+@@@%.",
    " ,S@@@*.     :@@@* ;*;::,,::;*; *@@@:     .*@@@S,",
    ".S@@@;       +@@@+ %@@@@@@@@@@% +@@@+       ;@@@S.",
    ";@@@*       .S@@@, ?@@@%SS%@@@? ,@@@S.       *@@@;",
    ":@@@%.     ,%@@@*  %@@@,  ,@@@%  *@@@%,     .%@@@:",
    ".*@@@#*++*?#@@@*. ,#@@S.  .S@@#, .*@@@#?*++*#@@@*.",
    "  :%@@@@@@@@#?:  ,S@@@;    ;@@@S,  :?#@@@@@@@@%:",
    "    .:+**+;:.  .+#@@@+      +@@@#+.  .:;+**+:.",
    " .+;,.      ,;*#@@@S:        :S@@@#*;,      .,;+.",
    ",S@@@#S%?%%#@@@@@%;.          .;%@@@@@#%%?%S#@@@S,",
    ".+?S#@@@@@@@#S?;,                ,;?S#@@@@@@@#S?+.",
    "    .,:::::,..                      ..,:::::,.",
]

# 'POLVO' in the figlet 'slant' font.
_WORDMARK = [
    "    ____  ____  __ _    ______",
    "   / __ \\/ __ \\/ /| |  / / __ \\",
    "  / /_/ / / / / / | | / / / / /",
    " / ____/ /_/ / /__| |/ / /_/ /",
    "/_/    \\____/_____/___/\\____/",
]


def banner_text() -> Text:
    """Build the welcome banner: octopus (left) + POLVO wordmark (right)."""
    art_w = max(len(row) for row in _OCTOPUS)
    word_w = max(len(row) for row in _WORDMARK)
    offset = (len(_OCTOPUS) - len(_WORDMARK)) // 2

    combined = Text(no_wrap=True, overflow="crop")
    for i, row in enumerate(_OCTOPUS):
        j = i - offset
        cell = _WORDMARK[j].ljust(word_w) if 0 <= j < len(_WORDMARK) else ""
        line = row.ljust(art_w) + "  " + cell
        combined.append(line.rstrip() + "\n")
    return combined


# Fixed width so the wide banner never soft-wraps on small terminals.
_BANNER_CONSOLE = Console(width=90)


def print_banner(console: Console | None = None) -> None:
    """Print the welcome banner (fixed 90-col console by default)."""
    target = console if console is not None else _BANNER_CONSOLE
    target.print(banner_text())