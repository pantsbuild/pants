from typing import Any, Callable, Generic, Dict, List, Tuple, Type, TypeVar

# TODO: black and flake8 disagree about the content of this file:
#   see https://github.com/psf/black/issues/1548
# flake8: noqa: E302

_In = TypeVar("_In")
_Out = TypeVar("_Out")

class PyDigest:
    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...

class PyExecutionRequest:
    def __init__(self, **kwargs: Any) -> None: ...

class PyExecutionStrategyOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyExecutor:
    def __init__(self, **kwargs: Any) -> None: ...

class PyGeneratorResponseBreak:
    val: Any
    def __init__(self, val: Any) -> None: ...

class PyGeneratorResponseGet(Generic[_Out, _In]):
    product: Type[_Out]
    declared_subject: Type[_In]
    subject: _In
    def __init__(self, product: Type[_Out], declared_subject: Type[_In], subject: _In) -> None: ...

class PyGeneratorResponseGetMulti(Generic[_Out]):
    gets: Tuple[PyGeneratorResponseGet[_Out, Any], ...]
    def __init__(self, gets: Tuple[PyGeneratorResponseGet[_Out, Any], ...]) -> None: ...

class PyGeneratorResponseThrow:
    err: Exception
    def __init__(self, err: Exception) -> None: ...

class PyNailgunServer:
    def __init__(self, **kwargs: Any) -> None: ...

class PyNailgunClient:
    def __init__(self, **kwargs: Any) -> None: ...
    def execute(
        self, signal_fn: Callable, command: str, args: List[str], env: Dict[str, str]
    ) -> int: ...

class PyRemotingOptions:
    def __init__(self, **kwargs: Any) -> None: ...

class PyScheduler:
    def __init__(self, **kwargs: Any) -> None: ...

class PySession:
    def __init__(self, **kwargs: Any) -> None: ...

class PyTasks:
    def __init__(self, **kwargs: Any) -> None: ...

class PyTypes:
    def __init__(self, **kwargs: Any) -> None: ...
