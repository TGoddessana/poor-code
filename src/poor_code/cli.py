from poor_code.app import PoorCodeApp
from poor_code.domain.echo_agent import EchoAgent


def main() -> None:
    PoorCodeApp(agent=EchoAgent()).run()
