class SiloError(Exception):
    """A problem the user can fix. The CLI prints the message without a traceback."""


class CommandFailed(SiloError):
    """A command a recipe ran exited with an error."""

    def __init__(self, message: str, command: str, exit_code: int) -> None:
        super().__init__(message)
        self.command = command
        self.exit_code = exit_code


class ResolutionError(SiloError):
    """The dependency graph could not be resolved."""


class InvalidConfiguration(SiloError):
    """Raised by a recipe's validate() when it cannot work with the resolved graph."""
