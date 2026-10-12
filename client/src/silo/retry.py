from collections.abc import Callable

from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

WAIT = wait_exponential_jitter(multiplier=2, max=30)


def retrying[T](
    what: str, attempt: Callable[[], T], gives_up: Callable[[BaseException], bool]
) -> T:
    """Run `attempt` up to three times. `gives_up` says which failures are final."""

    def announce(state: RetryCallState) -> None:
        assert state.outcome is not None and state.next_action is not None
        error = state.outcome.exception()
        print(f"{what} failed ({error}), trying again in {state.next_action.sleep:.0f}s")

    return Retrying(
        stop=stop_after_attempt(3),
        wait=WAIT,
        retry=retry_if_exception(lambda error: not gives_up(error)),
        before_sleep=announce,
        reraise=True,
    )(attempt)
