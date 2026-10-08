class SiloError(Exception):
    """A problem the user can fix. The CLI prints the message without a traceback."""


class ResolutionError(SiloError):
    """The dependency graph could not be resolved."""


class InvalidConfiguration(SiloError):
    """Raised by a recipe's validate() when it cannot work with the resolved graph."""
