# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import itertools
from dataclasses import dataclass
from functools import partial
from textwrap import dedent
from typing import (
    Any,
    Generator,
    Generic,
    Iterable,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from pants.engine.unions import union
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
class GetConstraints:
    output_type: Type
    input_type: Type

    @classmethod
    def parse_input_and_output_types(
        cls, get_args: Sequence[ast.expr], *, source_file_name: str
    ) -> Tuple[str, str]:
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
                    "Because you are using the shorthand form Get(OutputType, "
                    "InputType(constructor args), the second argument should be a constructor "
                    "call, like `MergeDigest(...)` or `Process(...)`."
                )
            if not hasattr(input_constructor.func, "id"):
                raise parse_error(
                    "Because you are using the shorthand form Get(OutputType, "
                    "InputType(constructor args), the second argument should be a top-level "
                    "constructor function call, like `MergeDigest(...)` or `Process(...)`, rather "
                    "than a method call."
                )
            return output_type, input_constructor.func.id  # type: ignore[attr-defined]

        input_type, _ = input_args
        if not isinstance(input_type, ast.Name):
            raise parse_error(
                "Because you are using the longhand form Get(OutputType, InputType, "
                "input), the second argument should be a type, like `MergeDigests` or "
                "`Process`."
            )
        return output_type, input_type.id


@frozen_after_init
@dataclass(unsafe_hash=True)
class Get(GetConstraints, Generic[_Output, _Input]):
    """Asynchronous generator API.

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

    @overload
    def __init__(self, output_type: Type[_Output], input_arg0: _Input) -> None:
        ...

    @overload
    def __init__(
        self,
        output_type: Type[_Output],
        input_arg0: Type[_Input],
        input_arg1: _Input,
    ) -> None:
        ...

    def __init__(
        self,
        output_type: Type[_Output],
        input_arg0: Union[Type[_Input], _Input],
        input_arg1: Optional[_Input] = None,
    ) -> None:
        self.output_type = self._validate_output_type(output_type)
        if input_arg1 is None:
            self.input_type = type(input_arg0)
            self.input = self._validate_input(input_arg0, shorthand_form=True)
        else:
            self.input_type = self._validate_explicit_input_type(input_arg0)
            self.input = self._validate_input(input_arg1, shorthand_form=False)

    @staticmethod
    def _validate_output_type(output_type: Any) -> Type[_Output]:
        if not isinstance(output_type, type):
            raise TypeError(
                "Invalid Get. The first argument (the output type) must be a type, but given "
                f"`{output_type}` with type {type(output_type)}."
            )
        return cast(Type[_Output], output_type)

    @staticmethod
    def _validate_explicit_input_type(input_type: Any) -> Type[_Input]:
        if not isinstance(input_type, type):
            raise TypeError(
                "Invalid Get. Because you are using the longhand form Get(OutputType, InputType, "
                f"input), the second argument must be a type, but given `{input_type}` of type "
                f"{type(input_type)}."
            )
        return cast(Type[_Input], input_type)

    def _validate_input(self, input_: Any, *, shorthand_form: bool) -> _Input:
        if isinstance(input_, type):
            if shorthand_form:
                raise TypeError(
                    "Invalid Get. Because you are using the shorthand form "
                    "Get(OutputType, InputType(constructor args)), the second argument should be "
                    f"a constructor call, rather than a type, but given {input_}."
                )
            else:
                raise TypeError(
                    "Invalid Get. Because you are using the longhand form "
                    "Get(OutputType, InputType, input), the third argument should be "
                    f"an object, rather than a type, but given {input_}."
                )
        # If the input_type is not annotated with `@union`, then we validate that the input is
        # exactly the same type as the input_type. (Why not check unions? We don't have access to
        # `UnionMembership` to know if it's a valid union member. The engine will check that.)
        if not union.is_instance(self.input_type) and type(input_) != self.input_type:
            # We can assume we're using the longhand form because the shorthand form guarantees
            # that the `input_type` is the same as `input`.
            raise TypeError(
                f"Invalid Get. The third argument `{input_}` must have the exact same type as the "
                f"second argument, {self.input_type}, but had the type {type(input_)}."
            )
        return cast(_Input, input_)

    def __await__(
        self,
    ) -> "Generator[Get[_Output, _Input], None, _Output]":
        """Allow a Get to be `await`ed within an `async` method, returning a strongly-typed result.

        The `yield`ed value `self` is interpreted by the engine within `extern_generator_send()` in
        `native.py`. This class will yield a single Get instance, which is converted into
        `PyGeneratorResponse::Get` from `externs.rs` via the python `cffi` library and the rust
        `cbindgen` crate.

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


@dataclass(frozen=True)
class _MultiGet:
    gets: Tuple[Get, ...]

    def __await__(self) -> Generator[Tuple[Get, ...], None, Tuple]:
        result = yield self.gets
        return cast(Tuple, result)


# These type variables are used to parameterize from 1 to 10 Gets when used in a tuple-style
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
async def MultiGet(__gets: Iterable[Get[_Output, _Input]]) -> Tuple[_Output, ...]:  # noqa: F811
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
) -> Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8, _Out9]:
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
) -> Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8]:
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
) -> Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7]:
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
) -> Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
    __get5: Get[_Out5, _In5],
) -> Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
    __get4: Get[_Out4, _In4],
) -> Tuple[_Out0, _Out1, _Out2, _Out3, _Out4]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0],
    __get1: Get[_Out1, _In1],
    __get2: Get[_Out2, _In2],
    __get3: Get[_Out3, _In3],
) -> Tuple[_Out0, _Out1, _Out2, _Out3]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_Out0, _In0], __get1: Get[_Out1, _In1], __get2: Get[_Out2, _In2]
) -> Tuple[_Out0, _Out1, _Out2]:
    ...


@overload
async def MultiGet(
    __get0: Get[_Out0, _In0], __get1: Get[_Out1, _In1]
) -> Tuple[_Out0, _Out1]:  # noqa: F811
    ...


async def MultiGet(  # noqa: F811
    __arg0: Union[Iterable[Get[_Output, _Input]], Get[_Out0, _In0]],
    __arg1: Optional[Get[_Out1, _In1]] = None,
    __arg2: Optional[Get[_Out2, _In2]] = None,
    __arg3: Optional[Get[_Out3, _In3]] = None,
    __arg4: Optional[Get[_Out4, _In4]] = None,
    __arg5: Optional[Get[_Out5, _In5]] = None,
    __arg6: Optional[Get[_Out6, _In6]] = None,
    __arg7: Optional[Get[_Out7, _In7]] = None,
    __arg8: Optional[Get[_Out8, _In8]] = None,
    __arg9: Optional[Get[_Out9, _In9]] = None,
) -> Union[
    Tuple[_Output, ...],
    Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8, _Out9],
    Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7, _Out8],
    Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6, _Out7],
    Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5, _Out6],
    Tuple[_Out0, _Out1, _Out2, _Out3, _Out4, _Out5],
    Tuple[_Out0, _Out1, _Out2, _Out3, _Out4],
    Tuple[_Out0, _Out1, _Out2, _Out3],
    Tuple[_Out0, _Out1, _Out2],
    Tuple[_Out0, _Out1],
    Tuple[_Out0],
]:
    """Yield a tuple of Get instances all at once.

    The `yield`ed value `self.gets` is interpreted by the engine within
    `extern_generator_send()` in `native.py`. This class will yield a tuple of Get instances,
    which is converted into `PyGeneratorResponse::GetMulti` from `externs.rs`.

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
    ):
        if any((__arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7, __arg8, __arg9)):
            raise ValueError()
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
    ):
        return await _MultiGet(
            (__arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7, __arg8, __arg9)
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
    ):
        return await _MultiGet((__arg0,))

    args = __arg0, __arg1, __arg2, __arg3, __arg4, __arg5, __arg6, __arg7, __arg8, __arg9

    def render_arg(arg: Any) -> Optional[str]:
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
            heterogenous tuple when all are complete. Currently up to 10 heterogenous Gets can be
            passed while still tracking their output types for type-checking by MyPy and similar
            type checkers.
            """
        )
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class Params:
    """A set of values with distinct types.

    Distinct types are enforced at consumption time by the rust type of the same name.
    """

    params: Tuple[Any, ...]

    def __init__(self, *args: Any) -> None:
        self.params = tuple(args)
