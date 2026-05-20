from textual.widgets import Static

_BANNER = r""" ____                  ____          _
|  _ \ ___   ___  _ __/ ___|___   __| | ___
| |_) / _ \ / _ \| '__| |   / _ \ / _` |/ _ \
|  __/ (_) | (_) | |  | |__| (_) | (_| |  __/
|_|   \___/ \___/|_|   \____\___/ \__,_|\___|"""


class Banner(Static):
    def __init__(self) -> None:
        super().__init__(_BANNER, classes="banner")
