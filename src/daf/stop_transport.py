"""Fence trusted adapter calls. Remote outcomes remain in their existing durable phases."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .contract import Refused
from .stop_control import StopControl


class StoppableTransport:
    def __init__(self, control: StopControl, transport: Any):
        self.control, self.transport = control, transport

    def __getattr__(self, name: str) -> Any:
        value = getattr(self.transport, name)
        if not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            # The original publication/CI journals retain ambiguous POST states.
            # "returned" means the local call ended, not remote work completed.
            with self.control.operation("transport:" + name, tracked_outcome=False):
                return value(*args, **kwargs)

        return call


def stoppable_run(control: StopControl, run: Callable[..., bytes]) -> Callable[..., bytes]:
    def call(argv: list[str], cwd: Path, **kwargs: Any) -> bytes:
        original = kwargs.pop("cancelled", lambda: False)
        with control.operation("subprocess", tracked_outcome=False) as identity:
            attempted = False

            def cancelled() -> bool:
                nonlocal attempted
                stopped = control.requested() or original()
                if stopped and not attempted:
                    control.cancellation(identity)
                    attempted = True
                return bool(stopped)

            try:
                return run(argv, cwd, cancelled=cancelled, **kwargs)
            except Refused as error:
                if str(error) == "execution_cancelled":
                    control.cancellation(identity, confirmed=True)
                raise

    return call
