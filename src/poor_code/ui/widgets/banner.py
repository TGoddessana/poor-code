from pathlib import Path

from textual.widgets import Static
from textwrap import dedent

from poor_code import __version__

_BANNER = dedent(rf""" 
   (\_/)   Poor-Code v{__version__}
   ( •_•)  cwd: {Path.cwd()}
   / >🥄""").rstrip()


class Banner(Static):
    def __init__(self) -> None:
        super().__init__(_BANNER, classes="banner")
