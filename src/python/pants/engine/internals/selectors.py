# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import itertools
from dataclasses import dataclass
from functools import partial
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
    input_type: type
    is_effect: bool

    @classmethod
    def signature_from_call_node(
        cls, call_node: ast.Call, *, source_file_name: str
    ) -> tuple[str, str, bool] | None:
        if not isinstance(call_node.func, ast.Name):
            return None
        if call_node.func.id not in ("Get", "Effect"):
            return None
        is_effect = call_node.func.id == "Effect"

        get_args = call_node.args

        parse_error = partial(GetParseError, get_args=get_args, source_file_name=source_file_name)

        if len(get_args) not in (2, 3):
            raise parse_error(
                f"Expected either two or three arguments, but got {len(get_args)} arguments."
            )

        output_expr = get_args[0]
        if not isinstance(output_expr, ast.Name):
            raise parse_error(
                "The first argument should be the output type, like `Digest` or `ProcessResult`."
            )
        output_type = output_expr.id

        input_args = get_args[1:]
        if len(input_args) == 1:
            input_constructor = input_args[0]
            if not isinstance(input_constructor, ast.Call):
                raise parse_error(
                    f"Because you are using the shorthand form {call_node.func.id}(OutputType, "
                    "InputType(constructor args), the second argument should be a constructor "
                    "call, like `MergeDigest(...)` or `Process(...)`."
                )
            if not hasattr(input_constructor.func, "id"):
                raise parse_error(
                    f"Because you are using the shorthand form {call_node.func.id}(OutputType, "
                    "InputType(constructor args), the second argument should be a top-level "
                    "constructor function call, like `MergeDigest(...)` or `Process(...)`, rather "
                    "than a method call."
                )
            return output_type, input_constructor.func.id, is_effect  # type: ignore[attr-defined]

        input_type, _ = input_args
        if not isinstance(input_type, ast.Name):
            raise parse_error(
                f"Because you are using the longhand form {call_node.func.id}(OutputType, "
                "InputType, input), the second argument should be a type, like `MergeDigests` or "
                "`Process`."
            )
        return output_type, input_type.id, is_effect

    def __repr__(self) -> str:
        name = "Effect" if self.is_effect else "Get"
        return f"{name}({self.output_type.__name__}, {self.input_type.__name__}, ..)"

    def __str__(self) -> str:
        return repr(self)


# TODO: Conditional needed until Python 3.8 allows the subscripted type to be used directly.
# see https://mypy.readthedocs.io/en/stable/runtime_troubles.html#using-classes-that-are-generic-in-stubs-but-not-at-runtime
if TYPE_CHECKING:

    class _BasePyGeneratorResponseGet(PyGeneratorResponseGet[_Output, _Input]):
        pass

else:

    class _BasePyGeneratorResponseGet(Generic[_Output, _Input], PyGeneratorResponseGet):
        pass


class Awaitable(Generic[_Output, _Input], _BasePyGeneratorResponseGet[_Output, _Input]):
    def __await__(
        self,
    ) -> Generator[Awaitable[_Output, _Input], None, _Output]:
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


class Effect(Generic[_Output, _Input], Awaitable[_Output, _Input]):
    """Asynchronous generator API for types which are SideEffecting.

    Unlike `Get`s, `Effect`s can cause side-effects (writing files to the workspace, publishing
    things, printing to the console), and so they may only be used in `@goal_rule`s.

    See Get for more information on supported syntaxes.
    """


class Get(Generic[_Output, _Input], Awaitable[_Output, _Input]):
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

_In0 = TypeVar("_In0")
_In1 = TypeVar("_In1")
_In2 = TypeVar("_In2")
_In3 = TypeVar("_In3")
_In4 = TypeVar("_In4")
_In5 = TypeVar("_In5")
_In6 = TypeVar("_In6")
_In7 = TypeVar("_In7")
_In8 = TypeVar("_In8")
_In9 = TypeVar("_In9")


@overload
async def MultiGet(__gets: Iterable[Get[_Output, _Input]]) -> tuple[_Output, ...]:  # noqa: F811
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Output, _Input],
    __get1: Get[_Output, _Input],
    __get2: Get[_Output, _Input],
    __get3: Get[_Output, _Input],
    __get4: Get[_Output, _Input],
    __get5: Get[_Output, _Input],
    __get6: Get[_Output, _Input],
    __get7: Get[_Output, _Input],
    __get8: Get[_Output, _Input],
    __get9: Get[_Output, _Input],
    __get10: Get[_Output, _Input],
    *__gets: Get[_Output, _Input],
) -> tuple[_Output, ...]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
    __get5: Get[_Out5, _In5],
    __get6: Get[_Out6, _In6],
    __get7: Get[_Out7, _In7],
    __get8: Get[_Out8, _In8],
    __get9: Get[_Out9, _In9],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8, _Out9]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
    __get5: Get[_Out5, _In5],
    __get6: Get[_Out6, _In6],
    __get7: Get[_Out7, _In7],
    __get8: Get[_Out8, _In8],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
    __get5: Get[_Out5, _In5],
    __get6: Get[_Out6, _In6],
    __get7: Get[_Out7, _In7],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
    __get5: Get[_Out5, _In5],
    __get6: Get[_Out6, _In6],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
    __get5: Get[_Out5, _In5],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
) -> tuple[_Out0, _Out1, _Out2, _Out3, _Out4]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
) -> tuple[_Out0, _Out1, _Out2, _Out3]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0], __get1: Get[_Out1, _In1], __get2: Get[_Out2, _In2]
) -> tuple[_Out0, _Out1, _Out2]:
    ...


@overload
async def MultiGet(
    __get0: Get[_Out0, _In0], __get1: Get[_Out1, _In1]
) -> tuple[_Out0, _Out1]:  # noqa: F811
    ...


async def MultiGet(  # noqa: F811
    __arg0: Iterable[Get[_Output, _Input]] | Get[_Out0, _In0],
    __arg1: Get[_Out1, _In1] | None = None,
    __arg2: Get[_Out2, _In2] | None = None,
    __arg3: Get[_Out3, _In3] | None = None,
    __arg4: Get[_Out4, _In4] | None = None,
    __arg5: Get[_Out5, _In5] | None = None,
    __arg6: Get[_Out6, _In6] | None = None,
    __arg7: Get[_Out7, _In7] | None = None,
    __arg8: Get[_Out8, _In8] | None = None,
    __arg9: Get[_Out9, _In9] | None = None,
    *__args: Get[_Output, _Input],
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
            return f"Get({arg.output_type.__name__}, {arg.input_type.__name__}, ...)"
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
            1. MultiGet(Iterable[Get[T]]) -> Tuple[T, ...]
            2. MultiGet(Get[T1], Get[T2], ...) -> Tuple[T1, T2, ...]

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
