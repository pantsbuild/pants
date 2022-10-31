# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import itertools
from dataclasses import dataclass
from textwrap import dedent
from typing import (
    TYPE_CHECKING,
    Any,
    Generator,
    Generic,
    Iterable,
    Sequence,
    Tuple,
    TypeVar,
    cast,
    overload,
)

from pants.engine.internals.native_engine import (
    PyGeneratorResponseBreak,
    PyGeneratorResponseGet,
    PyGeneratorResponseGetMulti,
)
from pants.util.meta import frozen_after_init

_Output = TypeVar("_Output")
_Input = TypeVar("_Input")


class GetParseError(ValueError):
    def __init__(
        self, explanation: str, *, get_args: Sequence[ast.expr], source_file_name: str
    ) -> None:
        def render_arg(expr: ast.expr) -> str:
            if isinstance(expr, ast.Name):
                return expr.id
            if isinstance(expr, ast.Call):
                # Check if it's a top-level function call.
                if hasattr(expr.func, "id"):
                    return f"{expr.func.id}()"  # type: ignore[attr-defined]
                # Check if it's a method call.
                if hasattr(expr.func, "attr") and hasattr(expr.func, "value"):
                    return f"{expr.func.value.id}.{expr.func.attr}()"  # type: ignore[attr-defined]

            # Fall back to the name of the ast node's class.
            return str(type(expr))

        rendered_args = ", ".join(render_arg(arg) for arg in get_args)
        # TODO: Add the line numbers for the `Get`. The number for `get_args[0].lineno` are
        #  off because they're relative to the wrapping rule.
        super().__init__(
            f"Invalid Get. {explanation} Failed for Get({rendered_args}) in {source_file_name}."
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class AwaitableConstraints:
    output_type: type
    input_types: tuple[type, ...]
    is_effect: bool

    def __repr__(self) -> str:
        name = "Effect" if self.is_effect else "Get"
        if len(self.input_types) == 0:
            inputs = ""
        elif len(self.input_types) == 1:
            inputs = f", {self.input_types[0].__name__}, .."
        else:
            input_items = ", ".join(f"{t.__name__}: .." for t in self.input_types)
            inputs = f", {{{input_items}}}"
        return f"{name}({self.output_type.__name__}{inputs})"

    def __str__(self) -> str:
        return repr(self)


# TODO: Conditional needed until Python 3.8 allows the subscripted type to be used directly.
# see https://mypy.readthedocs.io/en/stable/runtime_troubles.html#using-classes-that-are-generic-in-stubs-but-not-at-runtime
if TYPE_CHECKING:

    class _BasePyGeneratorResponseGet(PyGeneratorResponseGet[_Output]):
        pass

else:

    class _BasePyGeneratorResponseGet(Generic[_Output], PyGeneratorResponseGet):
        pass


class Awaitable(Generic[_Output], _BasePyGeneratorResponseGet[_Output]):
    def __await__(
        self,
    ) -> Generator[Awaitable[_Output], None, _Output]:
        """Allow a Get to be `await`ed within an `async` method, returning a strongly-typed result.

        The `yield`ed value `self` is interpreted by the engine within
        `native_engine_generator_send()`. This class will yield a single Get instance, which is
        a subclass of `PyGeneratorResponseGet`.

        This is how this method is eventually called:
        - When the engine calls an `async def` method decorated with `@rule`, an instance of
          `types.CoroutineType` is created.
        - The engine will call `.send(None)` on the coroutine, which will either:
          - raise StopIteration with a value (if the coroutine `return`s), or
          - return a `Get` instance to the engine (if the rule instead called `await Get(...)`).
        - The engine will fulfill the `Get` request to produce `x`, then call `.send(x)` and repeat the
          above until StopIteration.

        See more information about implementing this method at
        https://www.python.org/dev/peps/pep-0492/#await-expression.
        """
        result = yield self
        return cast(_Output, result)


class Effect(Generic[_Output], Awaitable[_Output]):
    """Asynchronous generator API for types which are SideEffecting.

    Unlike `Get`s, `Effect`s can cause side-effects (writing files to the workspace, publishing
    things, printing to the console), and so they may only be used in `@goal_rule`s.

    See Get for more information on supported syntaxes.
    """


class Get(Generic[_Output], Awaitable[_Output]):
    """Asynchronous generator API for side-effect-free types.

    A Get can be constructed in 2 ways with two variants each:

    + Long form:
        Get(<OutputType>, <InputType>, input)

    + Short form
        Get(<OutputType>, <InputType>(<constructor args for input>))

    The long form supports providing type information to the rule engine that it could not otherwise
    infer from the input variable [1]. Likewise, the short form must use inline construction of the
    input in order to convey the input type to the engine.

    [1] The engine needs to determine all rule and Get input and output types statically before
    executing any rules. Since Gets are declared inside function bodies, the only way to extract this
    information is through a parse of the rule function. The parse analysis is rudimentary and cannot
    infer more than names and calls; so a variable name does not give enough information to infer its
    type, only a constructor call unambiguously gives this information without more in-depth parsing
    that includes following imports and more.
    """


@dataclass(frozen=True)
class _MultiGet:
    gets: tuple[Get, ...]

    def __await__(self) -> Generator[tuple[Get, ...], None, tuple]:
        result = yield self.gets
        return cast(Tuple, result)


# These type variables are used to parametrize from 1 to 10 Gets when used in a tuple-style
# MultiGet call.

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
async def MultiGet(__gets: Iterable[Get[_Output]]) -> tuple[_Output, ...]:  # noqa: F811
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Output],
    __get1: Get[_Output],
    __get2: Get[_Output],
    __get3: Get[_Output],
    __get4: Get[_Output],
    __get5: Get[_Output],
    __get6: Get[_Output],
    __get7: Get[_Output],
    __get8: Get[_Output],
    __get9: Get[_Output],
    __get10: Get[_Output],
    *__gets: Get[_Output],
) -> tuple[_Output, ...]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0],
    __get1: Get[_Out1],
    __get2: Get[_Out2],
    __get3: Get[_Out3],
    __get4: Get[_Out4],
    __get5: Get[_Out5],
    __get6: Get[_Out6],
    __get7: Get[_Out7],
    __get8: Get[_Out8],
    __get9: Get[_Out9],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8, _Out9]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0],
    __get1: Get[_Out1],
    __get2: Get[_Out2],
    __get3: Get[_Out3],
    __get4: Get[_Out4],
    __get5: Get[_Out5],
    __get6: Get[_Out6],
    __get7: Get[_Out7],
    __get8: Get[_Out8],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0],
    __get1: Get[_Out1],
    __get2: Get[_Out2],
    __get3: Get[_Out3],
    __get4: Get[_Out4],
    __get5: Get[_Out5],
    __get6: Get[_Out6],
    __get7: Get[_Out7],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0],
    __get1: Get[_Out1],
    __get2: Get[_Out2],
    __get3: Get[_Out3],
    __get4: Get[_Out4],
    __get5: Get[_Out5],
    __get6: Get[_Out6],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0],
    __get1: Get[_Out1],
    __get2: Get[_Out2],
    __get3: Get[_Out3],
    __get4: Get[_Out4],
    __get5: Get[_Out5],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0],
    __get1: Get[_Out1],
    __get2: Get[_Out2],
    __get3: Get[_Out3],
    __get4: Get[_Out4],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0],
    __get1: Get[_Out1],
    __get2: Get[_Out2],
    __get3: Get[_Out3],
) -> tuple[_Out0, _Out1, _Out2, _Out3]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0], __get1: Get[_Out1], __get2: Get[_Out2]
) -> tuple[_Out0, _Out1, _Out2]:
    ...


@overload
async def MultiGet(__get0: Get[_Out0], __get1: Get[_Out1]) -> tuple[_Out0, _Out1]:  # noqa: F811
    ...


async def MultiGet(  # noqa: F811
    __arg0: Iterable[Get[_Output]] | Get[_Out0],
    __arg1: Get[_Out1] | None = None,
    __arg2: Get[_Out2] | None = None,
    __arg3: Get[_Out3] | None = None,
    __arg4: Get[_Out4] | None = None,
    __arg5: Get[_Out5] | None = None,
    __arg6: Get[_Out6] | None = None,
    __arg7: Get[_Out7] | None = None,
    __arg8: Get[_Out8] | None = None,
    __arg9: Get[_Out9] | None = None,
    *__args: Get[_Output],
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
    """Yield a tuple of Get instances all at once.

    The `yield`ed value `self.gets` is interpreted by the engine within
    `native_engine_generator_send()`. This class will yield a tuple of Get instances,
    which is converted into `PyGeneratorResponse::GetMulti`.

    The engine will fulfill these Get instances in parallel, and return a tuple of _Output
    instances to this method, which then returns this tuple to the `@rule` which called
    `await MultiGet(Get(_Output, ...) for ... in ...)`.
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
        return await _MultiGet(tuple(__arg0))

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and isinstance(__arg3, Get)
        and isinstance(__arg4, Get)
        and isinstance(__arg5, Get)
        and isinstance(__arg6, Get)
        and isinstance(__arg7, Get)
        and isinstance(__arg8, Get)
        and isinstance(__arg9, Get)
        and all(isinstance(arg, Get) for arg in __args)
    ):
        return await _MultiGet(
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

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and isinstance(__arg3, Get)
        and isinstance(__arg4, Get)
        and isinstance(__arg5, Get)
        and isinstance(__arg6, Get)
        and isinstance(__arg7, Get)
        and isinstance(__arg8, Get)
        and __arg9 is None
        and not __args
    ):
        return await _MultiGet(
            (__arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7, __arg8)
        )

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and isinstance(__arg3, Get)
        and isinstance(__arg4, Get)
        and isinstance(__arg5, Get)
        and isinstance(__arg6, Get)
        and isinstance(__arg7, Get)
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _MultiGet((__arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7))

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and isinstance(__arg3, Get)
        and isinstance(__arg4, Get)
        and isinstance(__arg5, Get)
        and isinstance(__arg6, Get)
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _MultiGet((__arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6))

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and isinstance(__arg3, Get)
        and isinstance(__arg4, Get)
        and isinstance(__arg5, Get)
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _MultiGet((__arg0, __arg1, __arg2, __arg3, __arg4, __arg5))

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and isinstance(__arg3, Get)
        and isinstance(__arg4, Get)
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _MultiGet((__arg0, __arg1, __arg2, __arg3, __arg4))

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and isinstance(__arg3, Get)
        and __arg4 is None
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _MultiGet((__arg0, __arg1, __arg2, __arg3))

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
        and isinstance(__arg2, Get)
        and __arg3 is None
        and __arg4 is None
        and __arg5 is None
        and __arg6 is None
        and __arg7 is None
        and __arg8 is None
        and __arg9 is None
        and not __args
    ):
        return await _MultiGet((__arg0, __arg1, __arg2))

    if (
        isinstance(__arg0, Get)
        and isinstance(__arg1, Get)
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
        return await _MultiGet((__arg0, __arg1))

    if (
        isinstance(__arg0, Get)
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
        return await _MultiGet((__arg0,))

    args = __arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7, __arg8, __arg9, *__args

    def render_arg(arg: Any) -> str | None:
        if arg is None:
            return None
        if isinstance(arg, Get):
            return repr(arg)
        return repr(arg)

    likely_args_exlicitly_passed = tuple(
        reversed(
            [
                render_arg(arg)
                for arg in itertools.dropwhile(lambda arg: arg is None, reversed(args))
            ]
        )
    )
    if any(arg is None for arg in likely_args_exlicitly_passed):
        raise ValueError(
            dedent(
                f"""\
                Unexpected MultiGet None arguments: {', '.join(
                    map(str, likely_args_exlicitly_passed)
                )}

                When constructing a MultiGet from individual Gets, all leading arguments must be
                Gets.
                """
            )
        )

    raise TypeError(
        dedent(
            f"""\
            Unexpected MultiGet argument types: {', '.join(map(str, likely_args_exlicitly_passed))}

            A MultiGet can be constructed in two ways:
            1. MultiGet(Iterable[Get[T]]) -> Tuple[T]
            2. MultiGet(Get[T1]], ...) -> Tuple[T1, T2, ...]

            The 1st form is intended for homogenous collections of Gets and emulates an
            async `for ...` comprehension used to iterate over the collection in parallel and
            collect the results in a homogenous tuple when all are complete.

            The 2nd form supports executing heterogeneous Gets in parallel and collecting them in a
            heterogeneous tuple when all are complete. Currently up to 10 heterogeneous Gets can be
            passed while still tracking their output types for type-checking by MyPy and similar
            type checkers. If more than 10 Gets are passed, type checking will enforce the Gets are
            homogeneous.
            """
        )
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class Params:
    """A set of values with distinct types.

    Distinct types are enforced at consumption time by the rust type of the same name.
    """

    params: tuple[Any, ...]

    def __init__(self, *args: Any) -> None:
        self.params = tuple(args)


def native_engine_generator_send(
    func, arg
) -> PyGeneratorResponseGet | PyGeneratorResponseGetMulti | PyGeneratorResponseBreak:
    try:
        res = func.send(arg)
        # It isn't necessary to differentiate between `Get` and `Effect` here, as the static
        # analysis of `@rule`s has already validated usage.
        if isinstance(res, (Get, Effect)):
            return res
        elif type(res) in (tuple, list):
            return PyGeneratorResponseGetMulti(res)
        else:
            raise ValueError(f"internal engine error: unrecognized coroutine result {res}")
    except StopIteration as e:
        if not e.args:
            raise
        # This was a `return` from a coroutine, as opposed to a `StopIteration` raised
        # by calling `next()` on an empty iterator.
        return PyGeneratorResponseBreak(e.value)
