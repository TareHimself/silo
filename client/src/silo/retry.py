import time
from collections.abc import Callable

DELAYS = (2.0, 8.0)


def retrying[T](what: str, attempt: Callable[[], T], gives_up: Callable[[Exception], bool]) -> T:
    """Run `attempt`, and again after a pause when it fails in a way that may pass.

    `gives_up` says which failures are final, such as a file that is not there.
    """
    for delay in DELAYS:
        try:
            return attempt()
        except Exception as error:
            if gives_up(error):
                raise
            print(f"{what} failed ({error}), trying again in {delay:g}s")
            time.sleep(delay)
    return attempt()
