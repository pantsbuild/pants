# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum

# NB: Avoid using "Optional" and use "| None" instead, as "Option" and "Optional" look similar.
from typing import TYPE_CHECKING, Any, Dict, Generic, Type, TypeVar, cast, overload

from pants.option import custom_types
from pants.util.frozendict import FrozenDict

if TYPE_CHECKING:
    from pants.option.subsystem import Subsystem

SubsystemT = TypeVar("SubsystemT", bound="Subsystem")
OptionT = TypeVar("OptionT", bound="OptionBase")
PropType = TypeVar("PropType")
StrT = TypeVar("StrT", str, "str | None")
IntT = TypeVar("IntT", int, "int | None")
FloatT = TypeVar("FloatT", float, "float | None")
BoolT = TypeVar("BoolT", bool, "bool | None")
EnumT = TypeVar("EnumT", bound=Enum)
ValueType = TypeVar("ValueType")
# NB: We don't provide constraints, as our `XListOption` types act like a set of contraints
ListMemberType = TypeVar("ListMemberType")


# ================================================================


class OptionBase(Generic[PropType]):
    """Descriptor for subsystem options.

    Clients shouldn't use this class directly, instead use one of the concrete classes below.

    This class serves two purposes:
        - Collect registration values for your option.
        - Provide a typed property for Python usage

    In order to define the `type` registration option, `self.option_type` must return a valid
    registration type. This can either be set using a class variable or by passing it into
    `__new__`.

    NOTE: Due to https://github.com/python/mypy/issues/5146 subclasses unfortunately need to provide
    overloaded `__new__` methods, as subclasses do not inherit overloaded function's annotations.
    Use one of the existing subclasses as a guide on how to do this.
    """

    flag_names: tuple[str, ...]
    kwargs: Dict
    option_type: Any  # NB: This should be some kind of callable that returns PropType

    # NB: Due to https://github.com/python/mypy/issues/5146, we try to keep the parameter list as
    # short as possible to avoid having to repeat the param in each of the 3 `__new__` specs that
    # each subclass must provide.
    # If you need additional information, this class follows the "Builder" pattern. Use the
    # "builder" methods to attach additional information. (E.g. see `advanced` method)
    # NB: We define `__new__` rather than `__init__` because otherwise subclasses would have to
    # define 3 `__new__`s AND `__init__`.
    def __new__(
        cls,
        *flag_names: str,
        default: Any,
        option_type: Type | None = None,
        help: str,
    ):
        self = super().__new__(cls)
        self.flag_names = flag_names
        if option_type is None:
            option_type = cls.option_type

        self.kwargs = dict(
            type=option_type,
            default=default,
            help=help,
        )
        return self

    @overload
    def __get__(self, obj: None, objtype: Any) -> OptionBase[PropType]:
        ...

    @overload
    def __get__(self, obj: object, objtype: Any) -> PropType:
        ...

    def __get__(self, obj, objtype):
        if obj is None:
            return self
        long_name = self.flag_names[-1]
        option_value = getattr(obj.options, long_name[2:].replace("-", "_"))
        if option_value is None:
            return None
        return self._convert_(option_value)

    # Subclasses can override if necessary
    def _convert_(self, val: Any) -> PropType:
        return cast("PropType", self.kwargs["type"](val))

    # ===== "Builder" Methods =====
    def advanced(self) -> OptionBase[PropType]:
        self.kwargs["advanced"] = True
        return self

    def from_file(self) -> OptionBase[PropType]:
        self.kwargs["fromfile"] = True
        return self

    def metavar(self, metavar: str, /) -> OptionBase[PropType]:
        self.kwargs["metavar"] = metavar
        return self

    def mutually_exclusive_group(self, mutually_exclusive_group: str, /) -> OptionBase[PropType]:
        self.kwargs["mutually_exclusive_group"] = mutually_exclusive_group
        return self

    def default_help_repr(self, default_help_repr: str, /) -> OptionBase[PropType]:
        self.kwargs["default_help_repr"] = default_help_repr
        return self

    def will_be_removed(self, *, version: str, hint: str) -> OptionBase[PropType]:
        self.kwargs["removal_version"] = version
        self.kwargs["removal_hint"] = hint
        return self

    # TODO: These only seem relevant on global options?
    def daemoned(self) -> OptionBase[PropType]:
        self.kwargs["daemon"] = True
        return self

    def non_fingerprinted(self) -> OptionBase[PropType]:
        self.kwargs["fingerprint"] = False
        return self


class ListOptionBase(OptionBase["tuple[ListMemberType, ...]"], Generic[ListMemberType]):
    """A homogenous list of options of some type.

    Don't use this class directly, instead use one of the conrete classes below.

    The default value will always be set as an empty list, and the Python property always returns
    a tuple (for immutability).

    In order to define the `member_type` registration option, `self.member_type` must return a valid
    list member type. This can either be set using a class variable or by passing it into `__new__`.
    """

    option_type = list
    member_type: Any

    def __new__(
        cls,
        *flag_names: str,
        member_type: ListMemberType | None = None,
        default: list[ListMemberType] | None = None,
        help: str,
    ):
        if member_type is None:
            member_type = cls.member_type

        default = default or []
        instance = super().__new__(
            cls,  # type: ignore[arg-type]
            *flag_names,
            default=default,
            help=help,
        )
        instance.kwargs["member_type"] = member_type
        return instance

    def _convert_(self, value: list[Any]) -> tuple[ListMemberType]:
        return cast("tuple[ListMemberType]", tuple(map(self.kwargs["member_type"], value)))


# ===== Concrete Classes =====


class StrOption(OptionBase[StrT]):
    """A string option."""

    option_type: Any = str

    @overload
    def __new__(cls, *flag_names: str, default: str, help: str) -> StrOption[str]:
        ...

    @overload
    def __new__(cls, *flag_names: str, help: str) -> StrOption[str | None]:
        ...

    def __new__(cls, *flag_names, default=None, help):
        return super().__new__(cls, *flag_names, default=default, help=help)


class IntOption(OptionBase[IntT]):
    """An int option."""

    option_type: Any = int

    @overload
    def __new__(cls, *flag_names: str, default: int, help: str) -> IntOption[int]:
        ...

    @overload
    def __new__(cls, *flag_names: str, help: str) -> IntOption[int | None]:
        ...

    def __new__(cls, *flag_names, default=None, help):
        return super().__new__(cls, *flag_names, default=default, help=help)


class FloatOption(OptionBase[FloatT]):
    """A float option."""

    option_type: Any = float

    @overload
    def __new__(cls, *flag_names: str, default: float, help: str) -> FloatOption[float]:
        ...

    @overload
    def __new__(cls, *flag_names: str, help: str) -> FloatOption[float | None]:
        ...

    def __new__(cls, *flag_names, default=None, help):
        return super().__new__(cls, *flag_names, default=default, help=help)


class BoolOption(OptionBase[BoolT]):
    """A bool option.

    If you don't provide a `default` value, this becomes a "tri-bool" where the property will return
    `None` if unset by the user.
    """

    option_type: Any = bool

    @overload
    def __new__(cls, *flag_names: str, default: bool, help: str) -> BoolOption[bool]:
        ...

    @overload
    def __new__(cls, *flag_names: str, help: str) -> BoolOption[bool | None]:
        ...

    def __new__(cls, *flag_names, default=None, help):
        return super().__new__(cls, *flag_names, default=default, help=help)


class EnumOption(OptionBase[PropType], Generic[PropType]):
    """An Enum option.

    If you provide a `default` parameter, the `option_type` parameter will be inferred from the type
    of the default. Otherwise, you'll need to provide the `option_type`.
    In either case, mypy will infer the correct Generic's type-parameter, so you shouldn't need to
    provide it.

    E.g.
        EnumOption(..., option_type=MyEnum)  # property type is deduced as `MyEnum | None`
        EnumOption(..., default=MyEnum.Value)  # property type is deduced as `MyEnum`
    """

    @overload
    def __new__(cls, *flag_names: str, default: EnumT, help: str) -> EnumOption[EnumT]:
        ...

    # N.B. This has an additional param for the no-default-provided case: `option_type`.
    @overload
    def __new__(
        cls, *flag_names: str, option_type: Type[EnumT], help: str
    ) -> EnumOption[EnumT | None]:
        ...

    def __new__(
        cls,
        *flag_names,
        option_type=None,
        default=None,
        help,
    ):
        if option_type is None:
            if default is None:
                raise ValueError("`option_type` must be provided if `default` isn't provided.")
            option_type = type(default)

        return super().__new__(
            cls, *flag_names, default=default, option_type=option_type, help=help
        )


class DictOption(OptionBase[FrozenDict[str, ValueType]], Generic[ValueType]):
    """A dictionary option mapping strings to client-provided `ValueType`.

    If you provide a `default` parameter, the `ValueType` type parameter will be inferred from the
    type of the values in the default. Otherwise, you'll need to provide `ValueType` if you want a
    non-`Any` type.

    E.g.
        # Explicit
        DictOption[str](...)  # property type is `FrozenDict[str, str]`
        DictOption[Any](..., default=dict(key="val"))  # property type is `FrozenDict[str, Any]`

        # Implicit
        DictOption(...)  # property type is `FrozenDict[str, Any]`
        DictOption(..., default={"key": "val"})  # property type is `FrozenDict[str, str]`
        DictOption(..., default=dict(key="val"))  # property type is `FrozenDict[str, str]`
        DictOption(..., default=dict(key=1))  # property type is `FrozenDict[str, int]`
        DictOption(..., default=dict(key1=1, key2="str"))  # property type is `FrozenDict[str, Any]`

    NOTE: Dictionary values are simply returned as parsed, and are not guaranteed to be of the
    `ValueType` specified.
    """

    option_type: Any = dict

    def __new__(cls, *flag_names, default: dict[str, ValueType] | None = None, help):
        return super().__new__(
            cls,  # type: ignore[arg-type]
            *flag_names,
            default=default or {},
            help=help,
        )

    def _convert_(self, val: Any) -> FrozenDict[str, ValueType]:
        return FrozenDict(val)


class TargetOption(StrOption):
    """A Pants Target option."""

    option_type: Any = custom_types.target_option


class DirOption(StrOption):
    """A directory option."""

    option_type: Any = custom_types.dir_option


class FileOption(StrOption):
    """A file option."""

    option_type: Any = custom_types.file_option


class ShellStrOption(StrOption):
    """A shell string option."""

    option_type: Any = custom_types.shell_str


class MemorySizeOption(IntOption):
    """A memory size option."""

    option_type: Any = custom_types.memory_size


class StrListOption(ListOptionBase[str]):
    """A homogenous list of string options."""

    member_type: Any = str


class IntListOption(ListOptionBase[int]):
    """A homogenous list of int options."""

    member_type: Any = int


class FloatListOption(ListOptionBase[float]):
    """A homogenous list of float options."""

    member_type: Any = float


class BoolListOption(ListOptionBase[bool]):
    """A homogenous list of bool options.

    @TODO: Tri-bool.
    """

    member_type: Any = bool


class EnumListOption(ListOptionBase[PropType], Generic[PropType]):
    """An homogenous list of Enum options.

    If you provide a `default` parameter, the `member_type` parameter will be inferred from the type
    of the first element of the default. Otherwise, you'll need to provide the `option_type`.
    In either case, mypy will infer the correct Generic's type-parameter, so you shouldn't need to
    provide it.

    E.g.
        EnumListOption(..., member_type=MyEnum)  # property type is deduced as `[MyEnum]`
        EnumListOption(..., default=[MyEnum.Value])  # property type is deduced as `[MyEnum]`
    """

    @overload
    def __new__(cls, *flag_names: str, default: list[EnumT], help: str) -> EnumListOption[EnumT]:
        ...

    # N.B. This has an additional param for the no-default-provided case: `member_type`.
    @overload
    def __new__(
        cls, *flag_names: str, member_type: Type[EnumT], help: str
    ) -> EnumListOption[EnumT]:
        ...

    def __new__(
        cls,
        *flag_names,
        member_type=None,
        default=None,
        help,
    ):
        if member_type is None:
            if default is None:
                raise ValueError("`member_type` must be provided if `default` isn't provided.")
            member_type = type(default[0])

        return super().__new__(
            cls, *flag_names, member_type=member_type, default=default, help=help
        )


class TargetListOption(StrListOption):
    """A homogenous list of target options."""

    member_type: Any = custom_types.target_option


class DirListOption(StrListOption):
    """A homogenous list of directory options."""

    member_type: Any = custom_types.dir_option


class FileListOption(StrListOption):
    """A homogenous list of file options."""

    member_type: Any = custom_types.file_option


class ShellStrListOption(StrListOption):
    """A homogenous list of shell string options."""

    member_type: Any = custom_types.shell_str


class MemorySizeListOption(IntListOption):
    """A homogenous list of memory size options."""

    member_type: Any = custom_types.memory_size


class ArgsListOption(ShellStrListOption):
    """A homogenous list of shell str options, to be used as arguments passed to some other tool.

    Clients can call `passthrough()` to set the "passthrough" flag. See `passthrough` for more info.
    """

    def __new__(cls, help: str):
        return super().__new__(
            cls,  # type: ignore[arg-type]
            "--args",
            help=help,
        )

    def passthrough(self) -> "ArgsListOption":
        """Set the "passthrough" flag.

        This should be used when callers can alternatively use "--" followed by the arguments,
        instead of having to provide "--[scope]-args='--arg1 --arg2'".
        """
        self.kwargs["passthrough"] = True
        return self


# @TODO: Add Dict Options
