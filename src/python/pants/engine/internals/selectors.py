# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from collections.abc import Coroutine, Generator, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar, cast, overload

from pants.engine.internals.native_engine import PyGeneratorResponseCall
from pants.util.strutil import softwrap

_Output = TypeVar("_Output")


@dataclass(frozen=True)
class AwaitableConstraints:
    rule_id: str
    output_type: type
    # The number of explicit positional arguments passed to a call-by-name awaitable.
    explicit_args_arity: int
    input_types: tuple[type, ...]
    is_effect: bool

    def __repr__(self) -> str:
        inputs = ", ".join(f"{t.__name__}" for t in self.input_types)
        return f"{self.rule_id}({inputs}) -> {self.output_type.__name__}"

    def __str__(self) -> str:
        return repr(self)


class Call(PyGeneratorResponseCall):
    def __await__(
        self,
    ) -> Generator[Any, None, Any]:
        result = yield self
        return result

    def __repr__(self) -> str:
        return f"Call({self.rule_id}(...) -> {self.output_type.__name__})"


@dataclass(frozen=True)
class _Concurrently:
    calls: tuple[Coroutine, ...]

    def __await__(self) -> Generator[tuple[Coroutine, ...], None, tuple]:
        result = yield self.calls
        return cast(tuple, result)


# These type variables are used to parametrize from 1 to 10 args when used in a tuple-style
# concurrently() call.

_Out0 = TypeVar("_Out0")
_Out1 = TypeVar("_Out1")
_Out2 = TypeVar("_Out2")
_Out3 = TypeVar("_Out3")
_Out4 = TypeVar("_Out4")
_Out5 = TypeVar("_Out5")
_Out6 = TypeVar("_Out6")
_Out7 = TypeVar("_Out7")
_Out8 = TypeVar("_Out8")
_Out9 = TypeVar("_Out9")


@overload
async def Concurrently(
    __gets: Iterable[Coroutine[Any, Any, _Output]],
) -> tuple[_Output, ...]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Output],
    __get1: Coroutine[Any, Any, _Output],
    __get2: Coroutine[Any, Any, _Output],
    __get3: Coroutine[Any, Any, _Output],
    __get4: Coroutine[Any, Any, _Output],
    __get5: Coroutine[Any, Any, _Output],
    __get6: Coroutine[Any, Any, _Output],
    __get7: Coroutine[Any, Any, _Output],
    __get8: Coroutine[Any, Any, _Output],
    __get9: Coroutine[Any, Any, _Output],
    __get10: Coroutine[Any, Any, _Output],
    *__gets: Coroutine[Any, Any, _Output],
) -> tuple[_Output, ...]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
    __get3: Coroutine[Any, Any, _Out3],
    __get4: Coroutine[Any, Any, _Out4],
    __get5: Coroutine[Any, Any, _Out5],
    __get6: Coroutine[Any, Any, _Out6],
    __get7: Coroutine[Any, Any, _Out7],
    __get8: Coroutine[Any, Any, _Out8],
    __get9: Coroutine[Any, Any, _Out9],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8, _Out9]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
    __get3: Coroutine[Any, Any, _Out3],
    __get4: Coroutine[Any, Any, _Out4],
    __get5: Coroutine[Any, Any, _Out5],
    __get6: Coroutine[Any, Any, _Out6],
    __get7: Coroutine[Any, Any, _Out7],
    __get8: Coroutine[Any, Any, _Out8],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
    __get3: Coroutine[Any, Any, _Out3],
    __get4: Coroutine[Any, Any, _Out4],
    __get5: Coroutine[Any, Any, _Out5],
    __get6: Coroutine[Any, Any, _Out6],
    __get7: Coroutine[Any, Any, _Out7],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
    __get3: Coroutine[Any, Any, _Out3],
    __get4: Coroutine[Any, Any, _Out4],
    __get5: Coroutine[Any, Any, _Out5],
    __get6: Coroutine[Any, Any, _Out6],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
    __get3: Coroutine[Any, Any, _Out3],
    __get4: Coroutine[Any, Any, _Out4],
    __get5: Coroutine[Any, Any, _Out5],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
    __get3: Coroutine[Any, Any, _Out3],
    __get4: Coroutine[Any, Any, _Out4],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
    __get3: Coroutine[Any, Any, _Out3],
) -> tuple[_Out0, _Out1, _Out2, _Out3]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
    __get2: Coroutine[Any, Any, _Out2],
) -> tuple[_Out0, _Out1, _Out2]: ...


@overload
async def Concurrently(
    __get0: Coroutine[Any, Any, _Out0],
    __get1: Coroutine[Any, Any, _Out1],
) -> tuple[_Out0, _Out1]: ...


async def Concurrently(
    __arg0: (Iterable[Coroutine[Any, Any, _Output]] | Coroutine[Any, Any, _Out0]),
    __arg1: Coroutine[Any, Any, _Out1] | None = None,
    __arg2: Coroutine[Any, Any, _Out2] | None = None,
    __arg3: Coroutine[Any, Any, _Out3] | None = None,
    __arg4: Coroutine[Any, Any, _Out4] | None = None,
    __arg5: Coroutine[Any, Any, _Out5] | None = None,
    __arg6: Coroutine[Any, Any, _Out6] | None = None,
    __arg7: Coroutine[Any, Any, _Out7] | None = None,
    __arg8: Coroutine[Any, Any, _Out8] | None = None,
    __arg9: Coroutine[Any, Any, _Out9] | None = None,
    *__args: Coroutine[Any, Any, _Output],
) -> (
    tuple[_Output, ...]
    | tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8, _Out9]
    | tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8]
    | tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7]
    | tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6]
    | tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5]
    | tuple[_Out0, _Out1, _Out2, _Out3, _Out4]
    | tuple[_Out0, _Out1, _Out2, _Out3]
    | tuple[_Out0, _Out1, _Out2]
    | tuple[_Out0, _Out1]
    | tuple[_Out0]
):
    """Yield a tuple of Coroutine instances all at once.

    The `yield`ed value `self.calls` is interpreted by the engine within
    `generator_send()`. This class will yield a tuple of Coroutine instances,
    which is converted into `PyGeneratorResponse::GetMulti`.

    The engine will fulfill these coroutines in parallel, and return a tuple of _Output
    instances to this method, which then returns this tuple to the `@rule` which called
    `await concurrently(...) for ... in ...)`.
    """
    if (
        isinstance(__arg0, Iterable)
        and __arg1 is None
        and __arg2 is None
        and __arg3 is None
        and __arg4 is None
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently(tuple(__arg0))

    if (
        isinstance(__arg0, Coroutine)
        and __arg1 is None
        and __arg2 is None
        and __arg3 is None
        and __arg4 is None
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0,))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and __arg2 is None
        and __arg3 is None
        and __arg4 is None
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0, __arg1))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and __arg3 is None
        and __arg4 is None
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0, __arg1, __arg2))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and isinstance(__arg3, Coroutine)
        and __arg4 is None
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0, __arg1, __arg2, __arg3))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and isinstance(__arg3, Coroutine)
        and isinstance(__arg4, Coroutine)
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0, __arg1, __arg2, __arg3, __arg4))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and isinstance(__arg3, Coroutine)
        and isinstance(__arg4, Coroutine)
        and isinstance(__arg5, Coroutine)
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0, __arg1, __arg2, __arg3, __arg4, __arg5))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and isinstance(__arg3, Coroutine)
        and isinstance(__arg4, Coroutine)
        and isinstance(__arg5, Coroutine)
        and isinstance(__arg6, Coroutine)
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and isinstance(__arg3, Coroutine)
        and isinstance(__arg4, Coroutine)
        and isinstance(__arg5, Coroutine)
        and isinstance(__arg6, Coroutine)
        and isinstance(__arg7, Coroutine)
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently((__arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7))

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and isinstance(__arg3, Coroutine)
        and isinstance(__arg4, Coroutine)
        and isinstance(__arg5, Coroutine)
        and isinstance(__arg6, Coroutine)
        and isinstance(__arg7, Coroutine)
        and isinstance(__arg8, Coroutine)
        and __arg9 is None
        and not __args
    ):
        return await _Concurrently(
            (__arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7, __arg8)
        )

    if (
        isinstance(__arg0, Coroutine)
        and isinstance(__arg1, Coroutine)
        and isinstance(__arg2, Coroutine)
        and isinstance(__arg3, Coroutine)
        and isinstance(__arg4, Coroutine)
        and isinstance(__arg5, Coroutine)
        and isinstance(__arg6, Coroutine)
        and isinstance(__arg7, Coroutine)
        and isinstance(__arg8, Coroutine)
        and isinstance(__arg9, Coroutine)
        and all(isinstance(arg, Coroutine) for arg in __args)
    ):
        return await _Concurrently(
            (
                __arg0,
                __arg1,
                __arg2,
                __arg3,
                __arg4,
                __arg5,
                __arg6,
                __arg7,
                __arg8,
                __arg9,
                *__args,
            )
        )

    args = __arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7, __arg8, __arg9, *__args

    def render_arg(arg: Any) -> str | None:
        if arg is None:
            return None
        return repr(arg)

    likely_args_explicitly_passed = tuple(
        reversed(
            [
                render_arg(arg)
                for arg in itertools.dropwhile(lambda arg: arg is None, reversed(args))
            ]
        )
    )
    if any(arg is None for arg in likely_args_explicitly_passed):
        raise ValueError(
            softwrap(
                f"""
                Unexpected concurrently() None arguments: {
                    ", ".join(map(str, likely_args_explicitly_passed))
                }

                When calling concurrently() on individual rule calls, all leading arguments must be
                awaitables.
                """
            )
        )

    raise TypeError(
        softwrap(
            f"""
            Unexpected concurrently() argument types: {", ".join(map(str, likely_args_explicitly_passed))}

            `concurrently` can be used in two ways:
              1. concurrently(Iterable[awaitable[T]]) -> Tuple[T]
              2. concurrently(awaitable[T1]], ...) -> Tuple[T1, T2, ...]

            The 1st form is intended for homogenous collections of rule calls and emulates an
            async `for ...` comprehension used to iterate over the collection in parallel and
            collect the results in a homogenous tuple when all are complete.

            The 2nd form supports executing heterogeneous rule calls in parallel and collecting
            them in a heterogeneous tuple when all are complete. Currently up to 10 heterogeneous
            rule calls can be passed while still tracking their output types for type-checking by
            MyPy and similar type checkers. If more than 10 rule calls are passed, type checking
            will enforce that they are homogeneous.
            """
        )
    )


concurrently = Concurrently


@dataclass(frozen=True)
class Params:
    """A set of values with distinct types.

    Distinct types are enforced at consumption time by the rust type of the same name.
    """

    params: tuple[Any, ...]

    def __init__(self, *args: Any) -> None:
        object.__setattr__(self, "params", tuple(args))
