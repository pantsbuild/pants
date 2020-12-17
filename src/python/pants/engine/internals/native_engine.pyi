from typing import Any, Callable, Dict, List, Tuple

# TODO: black and flake8 disagree about the content of this file:
#   see https://github.com/psf/black/issues/1548
# flake8: noqa: E302

def session_cancel_all() -> None: ...

class PyDigest:
    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...

class PySnapshot:
    def __init__(self) -> None: ...
    @property
    def digest(self) -> PyDigest: ...
    @property
    def dirs(self) -> Tuple[str, ...]: ...
    @property
    def files(self) -> Tuple[str, ...]: ...

class PyExecutionRequest:
    def __init__(self, **kwargs: Any) -> None: ...

class PyExecutionStrategyOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyExecutor:
    def __init__(self, **kwargs: Any) -> None: ...

class PyGeneratorResponseBreak:
    def __init__(self, **kwargs: Any) -> None: ...

class PyGeneratorResponseGet:
    def __init__(self, **kwargs: Any) -> None: ...

class PyGeneratorResponseGetMulti:
    def __init__(self, **kwargs: Any) -> None: ...

class PyNailgunServer:
    def __init__(self, **kwargs: Any) -> None: ...

class PyNailgunClient:
    def __init__(self, **kwargs: Any) -> None: ...
    def execute(self, command: str, args: List[str], env: Dict[str, str]) -> int: ...

class PyRemotingOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyScheduler:
    def __init__(self, **kwargs: Any) -> None: ...

class PySession:
    def __init__(self, **kwargs: Any) -> None: ...

class PySessionCancellationLatch:
    def __init__(self) -> None: ...

class PyTasks:
    def __init__(self, **kwargs: Any) -> None: ...

class PyTypes:
    def __init__(self, **kwargs: Any) -> None: ...
