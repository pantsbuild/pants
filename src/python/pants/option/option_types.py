# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast, overload

from pants.option import custom_types

if TYPE_CHECKING:
    pass

_PropType = TypeVar("_PropType")
_EnumT = TypeVar("_EnumT", bound=Enum)
_ValueType = TypeVar("_ValueType")
# NB: We don't provide constraints, as our `XListOption` types act like a set of contraints
_ListMemberType = TypeVar("_ListMemberType")


class _OptionBase(Generic[_PropType]):
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

    _flag_names: tuple[str, ...]
    _kwargs: dict
    option_type: Any  # NB: This should be some kind of callable that returns _PropType

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
        option_type: type | None = None,
        help: str,
    ):
        self = super().__new__(cls)
        self._flag_names = flag_names
        if option_type is None:
            option_type = cls.option_type

        self._kwargs = dict(
            type=option_type,
            default=default,
            help=help,
        )
        return self

    @property
    def flag_names(self) -> tuple[str, ...]:
        """Returns the flag names."""
        return self._flag_names

    @property
    def flag_options(self) -> dict:
        """Returns a shallow-copy of the the internal flag options."""
        return self._kwargs.copy()

    @overload
    def __get__(self, obj: None, objtype: Any) -> _OptionBase[_PropType]:
        ...

    @overload
    def __get__(self, obj: object, objtype: Any) -> _PropType:
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
    def _convert_(self, val: Any) -> _PropType:
        return cast("_PropType", self._kwargs["type"](val))

    def advanced(self) -> _OptionBase[_PropType]:
        self._kwargs["advanced"] = True
        return self

    def from_file(self) -> _OptionBase[_PropType]:
        self._kwargs["fromfile"] = True
        return self

    def metavar(self, metavar: str) -> _OptionBase[_PropType]:
        self._kwargs["metavar"] = metavar
        return self

    def mutually_exclusive_group(self, mutually_exclusive_group: str) -> _OptionBase[_PropType]:
        self._kwargs["mutually_exclusive_group"] = mutually_exclusive_group
        return self

    def default_help_repr(self, default_help_repr: str) -> _OptionBase[_PropType]:
        self._kwargs["default_help_repr"] = default_help_repr
        return self

    def deprecated(self, *, removal_version: str, hint: str) -> _OptionBase[_PropType]:
        self._kwargs["removal_version"] = removal_version
        self._kwargs["removal_hint"] = hint
        return self

    def daemoned(self) -> _OptionBase[_PropType]:
        self._kwargs["daemon"] = True
        return self

    def non_fingerprinted(self) -> _OptionBase[_PropType]:
        self._kwargs["fingerprint"] = False
        return self


class _ListOptionBase(_OptionBase["tuple[_ListMemberType, ...]"], Generic[_ListMemberType]):
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
        member_type: _ListMemberType | None = None,
        default: list[_ListMemberType] | None = None,
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
        instance._kwargs["member_type"] = member_type
        return instance

    def _convert_(self, value: list[Any]) -> tuple[_ListMemberType]:
        return cast("tuple[_ListMemberType]", tuple(map(self._kwargs["member_type"], value)))


# -----------------------------------------------------------------------------------------------
# Concrete Option Classes
# -----------------------------------------------------------------------------------------------


class StrOption(_OptionBase[_PropType]):
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


class IntOption(_OptionBase[_PropType]):
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


class FloatOption(_OptionBase[_PropType]):
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


class BoolOption(_OptionBase[_PropType]):
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


class EnumOption(_OptionBase[_PropType], Generic[_PropType]):
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
    def __new__(cls, *flag_names: str, default: _EnumT, help: str) -> EnumOption[_EnumT]:
        ...

    # N.B. This has an additional param for the no-default-provided case: `option_type`.
    @overload
    def __new__(
        cls, *flag_names: str, option_type: type[_EnumT], help: str
    ) -> EnumOption[_EnumT | None]:
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


class StrListOption(_ListOptionBase[str]):
    """A homogenous list of string options."""

    member_type: Any = str


class IntListOption(_ListOptionBase[int]):
    """A homogenous list of int options."""

    member_type: Any = int


class FloatListOption(_ListOptionBase[float]):
    """A homogenous list of float options."""

    member_type: Any = float


class BoolListOption(_ListOptionBase[bool]):
    """A homogenous list of bool options.

    @TODO: Tri-bool.
    """

    member_type: Any = bool


class EnumListOption(_ListOptionBase[_PropType], Generic[_PropType]):
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
    def __new__(cls, *flag_names: str, default: list[_EnumT], help: str) -> EnumListOption[_EnumT]:
        ...

    # N.B. This has an additional param for the no-default-provided case: `member_type`.
    @overload
    def __new__(
        cls, *flag_names: str, member_type: type[_EnumT], help: str
    ) -> EnumListOption[_EnumT]:
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
        self._kwargs["passthrough"] = True
        return self
