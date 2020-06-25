# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from textwrap import dedent
from typing import (
    Any,
    Generator,
    Generic,
    Iterable,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from pants.util.meta import frozen_after_init

# These type variables are used to type parameterize a `GetConstraints` (and consequently `Get`).
_ProductType = TypeVar("_ProductType")
# This type variable is used to type parameterize the subject of a `Get`.
_SubjectType = TypeVar("_SubjectType")


@frozen_after_init
@dataclass(unsafe_hash=True)
class GetConstraints(Generic[_ProductType, _SubjectType]):
    product_type: Type[_ProductType]
    subject_declared_type: Type[_SubjectType]


@frozen_after_init
@dataclass(unsafe_hash=True)
class Get(GetConstraints, Generic[_ProductType, _SubjectType]):
    """Asynchronous generator API.

    A Get can be constructed in 2 ways with two variants each:

    + Long form:
        Get(<ProductType>, <SubjectType>, subject)

    + Short form
        Get(<ProductType>, <SubjectType>(<constructor args for subject>))

    The long form supports providing type information to the rule engine that it could not otherwise
    infer from the subject variable [1]. Likewise, the short form must use inline construction of the
    subject in order to convey the subject type to the engine.

    The `weak` parameter is an experimental extension: a "weak" Get will return None rather than the
    requested value iff the dependency caused by the Get would create a cycle in the dependency
    graph.

    [1] The engine needs to determine all rule and Get input and output types statically before
    executing any rules. Since Gets are declared inside function bodies, the only way to extract this
    information is through a parse of the rule function. The parse analysis is rudimentary and cannot
    infer more than names and calls; so a variable name does not give enough information to infer its
    type, only a constructor call unambiguously gives this information without more in-depth parsing
    that includes following imports and more.
    """

    @overload
    def __init__(
        self, product_type: Type[_ProductType], subject_arg0: _SubjectType, *, weak: bool = False
    ) -> None:
        ...

    @overload
    def __init__(
        self,
        product_type: Type[_ProductType],
        subject_arg0: Type[_SubjectType],
        subject_arg1: _SubjectType,
        *,
        weak: bool = False,
    ) -> None:
        ...

    def __init__(
        self,
        product_type: Type[_ProductType],
        subject_arg0: Union[Type[_SubjectType], _SubjectType],
        subject_arg1: Optional[_SubjectType] = None,
        *,
        weak: bool = False,
    ) -> None:
        self.product_type = product_type
        self.subject_declared_type: Type[_SubjectType] = self._validate_subject_declared_type(
            subject_arg0 if subject_arg1 is not None else type(subject_arg0)
        )
        self.subject: _SubjectType = self._validate_subject(
            subject_arg1 if subject_arg1 is not None else subject_arg0
        )
        self.weak = weak

        self._validate_product()

    def _validate_product(self) -> None:
        if not isinstance(self.product_type, type):
            raise TypeError(
                f"The product type argument must be a type, given {self.product_type} of type "
                f"{type(self.product_type)}."
            )

    @staticmethod
    def _validate_subject_declared_type(subject_declared_type: Any) -> Type[_SubjectType]:
        if not isinstance(subject_declared_type, type):
            raise TypeError(
                f"The subject declared type argument must be a type, given {subject_declared_type} "
                f"of type {type(subject_declared_type)}."
            )
        return cast(Type[_SubjectType], subject_declared_type)

    @staticmethod
    def _validate_subject(subject: Any) -> _SubjectType:
        if isinstance(subject, type):
            raise TypeError(f"The subject argument cannot be a type, given {subject}.")
        return cast(_SubjectType, subject)

    def __await__(self,) -> ("Generator[Get[_ProductType, _SubjectType], None, _ProductType]"):
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
        return cast(_ProductType, result)


@dataclass(frozen=True)
class _MultiGet:
    gets: Tuple[Get, ...]

    def __await__(self) -> Generator[Tuple[Get, ...], None, Tuple]:
        result = yield self.gets
        return cast(Tuple, result)


# These type variables are used to parameterize from 1 to 10 Gets when used in a tuple-style
# MultiGet call.

_P0 = TypeVar("_P0")
_P1 = TypeVar("_P1")
_P2 = TypeVar("_P2")
_P3 = TypeVar("_P3")
_P4 = TypeVar("_P4")
_P5 = TypeVar("_P5")
_P6 = TypeVar("_P6")
_P7 = TypeVar("_P7")
_P8 = TypeVar("_P8")
_P9 = TypeVar("_P9")

_SDT0 = TypeVar("_SDT0")
_SDT1 = TypeVar("_SDT1")
_SDT2 = TypeVar("_SDT2")
_SDT3 = TypeVar("_SDT3")
_SDT4 = TypeVar("_SDT4")
_SDT5 = TypeVar("_SDT5")
_SDT6 = TypeVar("_SDT6")
_SDT7 = TypeVar("_SDT7")
_SDT8 = TypeVar("_SDT8")
_SDT9 = TypeVar("_SDT9")

_S0 = TypeVar("_S0")
_S1 = TypeVar("_S1")
_S2 = TypeVar("_S2")
_S3 = TypeVar("_S3")
_S4 = TypeVar("_S4")
_S5 = TypeVar("_S5")
_S6 = TypeVar("_S6")
_S7 = TypeVar("_S7")
_S8 = TypeVar("_S8")
_S9 = TypeVar("_S9")


@overload
async def MultiGet(
    __gets: Iterable[Get[_ProductType, _SubjectType]]
) -> Tuple[_ProductType, ...]:  # noqa: F811
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0],
    __get1: Get[_P1, _S1],
    __get2: Get[_P2, _S2],
    __get3: Get[_P3, _S3],
    __get4: Get[_P4, _S4],
    __get5: Get[_P5, _S5],
    __get6: Get[_P6, _S6],
    __get7: Get[_P7, _S7],
    __get8: Get[_P8, _S8],
    __get9: Get[_P9, _S9],
) -> Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6, _P7, _P8, _P9]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0],
    __get1: Get[_P1, _S1],
    __get2: Get[_P2, _S2],
    __get3: Get[_P3, _S3],
    __get4: Get[_P4, _S4],
    __get5: Get[_P5, _S5],
    __get6: Get[_P6, _S6],
    __get7: Get[_P7, _S7],
    __get8: Get[_P8, _S8],
) -> Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6, _P7, _P8]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0],
    __get1: Get[_P1, _S1],
    __get2: Get[_P2, _S2],
    __get3: Get[_P3, _S3],
    __get4: Get[_P4, _S4],
    __get5: Get[_P5, _S5],
    __get6: Get[_P6, _S6],
    __get7: Get[_P7, _S7],
) -> Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6, _P7]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0],
    __get1: Get[_P1, _S1],
    __get2: Get[_P2, _S2],
    __get3: Get[_P3, _S3],
    __get4: Get[_P4, _S4],
    __get5: Get[_P5, _S5],
    __get6: Get[_P6, _S6],
) -> Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0],
    __get1: Get[_P1, _S1],
    __get2: Get[_P2, _S2],
    __get3: Get[_P3, _S3],
    __get4: Get[_P4, _S4],
    __get5: Get[_P5, _S5],
) -> Tuple[_P0, _P1, _P2, _P3, _P4, _P5]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0],
    __get1: Get[_P1, _S1],
    __get2: Get[_P2, _S2],
    __get3: Get[_P3, _S3],
    __get4: Get[_P4, _S4],
) -> Tuple[_P0, _P1, _P2, _P3, _P4]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0], __get1: Get[_P1, _S1], __get2: Get[_P2, _S2], __get3: Get[_P3, _S3],
) -> Tuple[_P0, _P1, _P2, _P3]:
    ...


@overload
async def MultiGet(  # noqa: F811
    __get0: Get[_P0, _S0], __get1: Get[_P1, _S1], __get2: Get[_P2, _S2]
) -> Tuple[_P0, _P1, _P2]:
    ...


@overload
async def MultiGet(__get0: Get[_P0, _S0], __get1: Get[_P1, _S1]) -> Tuple[_P0, _P1]:  # noqa: F811
    ...


async def MultiGet(  # noqa: F811
    __arg0: Union[Iterable[Get[_ProductType, _SubjectType]], Get[_P0, _S0]],
    __arg1: Optional[Get[_P1, _S1]] = None,
    __arg2: Optional[Get[_P2, _S2]] = None,
    __arg3: Optional[Get[_P3, _S3]] = None,
    __arg4: Optional[Get[_P4, _S4]] = None,
    __arg5: Optional[Get[_P5, _S5]] = None,
    __arg6: Optional[Get[_P6, _S6]] = None,
    __arg7: Optional[Get[_P7, _S7]] = None,
    __arg8: Optional[Get[_P8, _S8]] = None,
    __arg9: Optional[Get[_P9, _S9]] = None,
) -> Union[
    Tuple[_ProductType, ...],
    Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6, _P7, _P8, _P9],
    Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6, _P7, _P8],
    Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6, _P7],
    Tuple[_P0, _P1, _P2, _P3, _P4, _P5, _P6],
    Tuple[_P0, _P1, _P2, _P3, _P4, _P5],
    Tuple[_P0, _P1, _P2, _P3, _P4],
    Tuple[_P0, _P1, _P2, _P3],
    Tuple[_P0, _P1, _P2],
    Tuple[_P0, _P1],
    Tuple[_P0],
]:
    """Yield a tuple of Get instances all at once.

    The `yield`ed value `self.gets` is interpreted by the engine within
    `extern_generator_send()` in `native.py`. This class will yield a tuple of Get instances,
    which is converted into `PyGeneratorResponse::GetMulti` from `externs.rs`.

    The engine will fulfill these Get instances in parallel, and return a tuple of _Product
    instances to this method, which then returns this tuple to the `@rule` which called
    `await MultiGet(Get[_Product](...) for ... in ...)`.
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
            return f"Get({arg.product_type.__name__}, {arg.subject_declared_type.__name__}, ...)"
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

                When constructing a MultiGet from individual Gets all leading arguments must be
                Gets.
                """
            )
        )

    raise TypeError(
        dedent(
            f"""\
            Unexpected MultiGet argument types: {', '.join(map(str, likely_args_exlicitly_passed))}

            A MultiGet can be constructed in two ways:
            1. MultiGet(Iterable[Get[P]]) -> Tuple[P, ...]
            2. MultiGet(Get[P1], Get[P2], ...) -> Tuple[P1, P2, ...]

            The 1st form is intended for homogenous collections of Gets and emulates an
            async for ... comprehension used to iterate over the collection in parallel and collect
            the results in a homogenous Tuple when all are complete.

            The 2nd form supports executing heterogeneous Gets in parallel and collecting them in a
            heterogenous tuple when all are complete. Currently up to 10 heterogenous Gets can be
            passed while still tracking their product types for type-checking by MyPy and similar
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
