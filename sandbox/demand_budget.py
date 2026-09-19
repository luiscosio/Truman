"""One shared wall-clock deadline for all calls in a generation attempt."""
import time


def remaining(store, default=240):
    deadline = getattr(store, 'deadline', None)
    if deadline is None:
        return default
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError('World generation deadline exceeded')
    return min(default, seconds)
