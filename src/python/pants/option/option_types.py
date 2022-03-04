# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar, Union, cast, overload

from pants.option import custom_types
from pants.util.docutil import bin_name

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class OptionsInfo:
    flag_names: tuple[str, ...]
    flag_options: dict[str, Any]


# The type of the option.
_OptT = TypeVar("_OptT")
# The type of option's default (may be _OptT or some other type like `None`)
_DefaultT = TypeVar("_DefaultT")
# The type of pants.option.subsystem.Subsystem classes.
# NB: Ideally this would be `type[Subsystem]`, however where this type is used is generally
# provided untyped lambdas.
_SubsystemType = Any
# A "dynamic" value type. This exists to allow clients to provide callable arguments taking the
# subsytem type and returning a value. E.g. `prop = Option(..., default=lambda cls: cls.default)`.
# This is necessary to support "base" subsystem types which are subclassed with more specific
# values.
# NB: Marking this as `Callable[[_SubsystemType], _DefaultT]` will upset mypy at the call site
# because mypy won't be able to have enough info to deduce the correct type.
_DynamicDefaultT = Callable[[_SubsystemType], Any]
# The type of the `default` parameter for each option.
_MaybeDynamicT = Union[_DynamicDefaultT, _DefaultT]
# The type of the `help` parameter for each option.
_HelpT = _MaybeDynamicT[str]


def _eval_maybe_dynamic(val: _MaybeDynamicT[_DefaultT], subsystem_cls: _SubsystemType) -> _DefaultT:
    return val(subsystem_cls) if inspect.isfunction(val) else val  # type: ignore[operator,return-value,no-any-return]


class _OptionBase(Generic[_OptT, _DefaultT]):
    """Descriptor base for subsystem options.

    Clients shouldn't use this class directly, instead use one of the concrete classes below.

    This class serves two purposes:
        - Collect registration values for your option.
        - Provide a typed property for Python usage
    """

    _flag_names: tuple[str, ...]
    _default: _MaybeDynamicT[_DefaultT]
    _help: _HelpT
    _register_if: Callable[[_SubsystemType], bool]
    _extra_kwargs: dict[str, Any]

    # NB: We define `__new__` rather than `__init__` because some subclasses need to define
    # `__new__` and mypy has issues if your class defines both.
    def __new__(
        cls,
        *flag_names: str,
        default: _MaybeDynamicT[_DefaultT],
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = None,
        daemon: bool | None = None,
        default_help_repr: str | None = None,
        fingerprint: bool | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_hint: str | None = None,
        removal_version: str | None = None,
    ):
        self = super().__new__(cls)
        self._flag_names = flag_names
        self._default = default
        self._help = help
        self._register_if = register_if or (lambda cls: True)
        self._extra_kwargs = {
            k: v
            for k, v in {
                "advanced": advanced,
                "daemon": daemon,
                "default_help_repr": default_help_repr,
                "fingerprint": fingerprint,
                "fromfile": fromfile,
                "metavar": metavar,
                "mutually_exclusive_group": mutually_exclusive_group,
                "removal_hint": removal_hint,
                "removal_version": removal_version,
            }.items()
            if v is not None
        }
        return self

    # Subclasses can override if necessary
    def get_option_type(self, subsystem_cls):
        return type(self).option_type

    # Subclasses can override if necessary
    def _convert_(self, val: Any) -> _OptT:
        return cast("_OptT", val)

    def get_flag_options(self, subsystem_cls) -> dict:
        return dict(
            help=_eval_maybe_dynamic(self._help, subsystem_cls),
            default=_eval_maybe_dynamic(self._default, subsystem_cls),
            type=self.get_option_type(subsystem_cls),
            **self._extra_kwargs,
        )

    @overload
    def __get__(self, obj: None, objtype: Any) -> OptionsInfo | None:
        ...

    @overload
    def __get__(self, obj: object, objtype: Any) -> _OptT | _DefaultT:
        ...

    def __get__(self, obj, objtype):
        if obj is None:
            if self._register_if(objtype):
                return OptionsInfo(self._flag_names, self.get_flag_options(objtype))
            return None
        long_name = self._flag_names[-1]
        option_value = getattr(obj.options, long_name[2:].replace("-", "_"))
        if option_value is None:
            return None
        return self._convert_(option_value)


# The type of the list members.
# NB: We don't provide constraints, as our `XListOption` types act like a set of contraints
_ListMemberT = TypeVar("_ListMemberT")


class _ListOptionBase(
    _OptionBase["tuple[_ListMemberT, ...]", "tuple[_ListMemberT, ...]"],
    Generic[_ListMemberT],
):
    """Descriptor base for a  subsystem option of  ahomogenous list of some type.

    Don't use this class directly, instead use one of the conrete classes below.

    The default value will always be set as an empty list, and the Python property always returns
    a tuple (for immutability).
    """

    option_type = list

    def __new__(
        cls,
        *flag_names: str,
        default: _MaybeDynamicT[list[_ListMemberT]] = [],
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = None,
        daemon: bool | None = None,
        default_help_repr: str | None = None,
        fingerprint: bool | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_hint: str | None = None,
        removal_version: str | None = None,
    ):
        default = default or []
        instance = super().__new__(
            cls,  # type: ignore[arg-type]
            *flag_names,
            default=default,  # type: ignore[arg-type]
            help=help,
            register_if=register_if,
            advanced=advanced,
            daemon=daemon,
            default_help_repr=default_help_repr,
            fingerprint=fingerprint,
            fromfile=fromfile,
            metavar=metavar,
            mutually_exclusive_group=mutually_exclusive_group,
            removal_hint=removal_hint,
            removal_version=removal_version,
        )
        return instance

    # Subclasses can override if necessary
    def get_member_type(self, subsystem_cls):
        return type(self).member_type

    # Subclasses can override if necessary
    def _convert_(self, value: list[Any]) -> tuple[_ListMemberT]:
        return cast("tuple[_ListMemberT]", tuple(value))

    def get_flag_options(self, subsystem_cls) -> dict[str, Any]:
        return dict(
            member_type=self.get_member_type(subsystem_cls),
            **super().get_flag_options(subsystem_cls),
        )


# -----------------------------------------------------------------------------------------------
# String Concrete Option Classes
# -----------------------------------------------------------------------------------------------
_StrDefault = TypeVar("_StrDefault", str, None)


class StrOption(_OptionBase[str, _StrDefault]):
    """A string option."""

    option_type: Any = str


class StrListOption(_ListOptionBase[str]):
    """A homogenous list of string options."""

    member_type: Any = str


class TargetOption(_OptionBase[str, _StrDefault]):
    """A Pants Target option."""

    option_type: Any = custom_types.target_option


class TargetListOption(StrListOption):
    """A homogenous list of target options."""

    member_type: Any = custom_types.target_option


class DirOption(_OptionBase[str, _StrDefault]):
    """A directory option."""

    option_type: Any = custom_types.dir_option


class DirListOption(StrListOption):
    """A homogenous list of directory options."""

    member_type: Any = custom_types.dir_option


class FileOption(_OptionBase[str, _StrDefault]):
    """A file option."""

    option_type: Any = custom_types.file_option


class FileListOption(StrListOption):
    """A homogenous list of file options."""

    member_type: Any = custom_types.file_option


class ShellStrOption(_OptionBase[str, _StrDefault]):
    """A shell string option."""

    option_type: Any = custom_types.shell_str


class ShellStrListOption(StrListOption):
    """A homogenous list of shell string options."""

    member_type: Any = custom_types.shell_str


class WorkspacePathOption(_OptionBase[str, _StrDefault]):
    """A workspace path option."""

    option_type: Any = custom_types.workspace_path


# -----------------------------------------------------------------------------------------------
# Int Concrete Option Classes
# -----------------------------------------------------------------------------------------------
_IntDefault = TypeVar("_IntDefault", int, None)


class IntOption(_OptionBase[int, _IntDefault]):
    """An int option."""

    option_type: Any = int


class IntListOption(_ListOptionBase[int]):
    """A homogenous list of int options."""

    member_type: Any = int


class MemorySizeOption(_OptionBase[int, _IntDefault]):
    """A memory size option."""

    option_type: Any = custom_types.memory_size


class MemorySizeListOption(IntListOption):
    """A homogenous list of memory size options."""

    member_type: Any = custom_types.memory_size


_FloatDefault = TypeVar("_FloatDefault", float, None)


class FloatOption(_OptionBase[float, _FloatDefault]):
    """A float option."""

    option_type: Any = float


class FloatListOption(_ListOptionBase[float]):
    """A homogenous list of float options."""

    member_type: Any = float


# -----------------------------------------------------------------------------------------------
# Bool Concrete Option Classes
# -----------------------------------------------------------------------------------------------
_BoolDefault = TypeVar("_BoolDefault", bool, None)


class BoolOption(_OptionBase[bool, _BoolDefault]):
    """A bool option.

    If you don't provide a `default` value, this becomes a "tri-bool" where the property will return
    `None` if unset by the user.
    """

    option_type: Any = bool


class BoolListOption(_ListOptionBase[bool]):
    """A homogenous list of bool options."""

    member_type: Any = bool


# -----------------------------------------------------------------------------------------------
# Enum Concrete Option Classes
# -----------------------------------------------------------------------------------------------
_EnumT = TypeVar("_EnumT", bound=Enum)


class EnumOption(_OptionBase[_OptT, _DefaultT]):
    """An Enum option.

    - If you provide a static non-None `default` parameter, the `enum_type` parameter will be
        inferred from the type of the the default.
    - If you provide a dynamic `default` or `default` is `None`, you must also provide `enum_type`.

    E.g.
        # The property type is `MyEnum`
        EnumOption(..., default=MyEnum.Value)
        EnumOption(..., enum_type=MyEnum default=lambda cls: cls.default_val)

        # The property type is `MyEnum | None`
        EnumOption(..., enum_type=MyEnum, default=None)
    """

    @overload
    def __new__(
        cls,
        *flag_names: str,
        default: _EnumT,
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = None,
        daemon: bool | None = None,
        default_help_repr: str | None = None,
        fingerprint: bool | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_hint: str | None = None,
        removal_version: str | None = None,
    ) -> EnumOption[_EnumT, _EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: dynamic default
    def __new__(
        cls,
        *flag_names: str,
        enum_type: type[_EnumT],
        default: _DynamicDefaultT,
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = None,
        daemon: bool | None = None,
        default_help_repr: str | None = None,
        fingerprint: bool | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_hint: str | None = None,
        removal_version: str | None = None,
    ) -> EnumOption[_EnumT, _EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: default is `None`
    def __new__(
        cls,
        *flag_names: str,
        enum_type: type[_EnumT],
        default: None,
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = None,
        daemon: bool | None = None,
        default_help_repr: str | None = None,
        fingerprint: bool | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_hint: str | None = None,
        removal_version: str | None = None,
    ) -> EnumOption[_EnumT, None]:
        ...

    def __new__(
        cls,
        *flag_names,
        enum_type=None,
        default,
        help,
        register_if=None,
        # Additional bells/whistles
        advanced=None,
        daemon=None,
        default_help_repr=None,
        fingerprint=None,
        fromfile=None,
        metavar=None,
        mutually_exclusive_group=None,
        removal_hint=None,
        removal_version=None,
    ):
        instance = super().__new__(
            cls,
            *flag_names,
            default=default,
            help=help,
            register_if=register_if,
            advanced=advanced,
            daemon=daemon,
            default_help_repr=default_help_repr,
            fingerprint=fingerprint,
            fromfile=fromfile,
            metavar=metavar,
            mutually_exclusive_group=mutually_exclusive_group,
            removal_hint=removal_hint,
            removal_version=removal_version,
        )
        instance._enum_type = enum_type
        return instance

    def get_option_type(self, subsystem_cls):
        enum_type = self._enum_type
        default = _eval_maybe_dynamic(self._default, subsystem_cls)
        if enum_type is None:
            if default is None:
                raise ValueError(
                    "`enum_type` must be provided to the constructor if `default` isn't provided."
                )
            return type(default)
        elif default is not None and not isinstance(default, enum_type):
            raise ValueError(
                f"Expected the default value to be of type '{enum_type}', got '{type(default)}'"
            )
        return enum_type


class EnumListOption(_ListOptionBase[_OptT], Generic[_OptT]):
    """An homogenous list of Enum options.

    - If you provide a static `default` parameter, the `enum_type` parameter will be inferred from
        the type of the first element of the default.
    - If you provide a dynamic `default` or provide no default, you must also provide `enum_type`.

    E.g. In all 3 cases the property type is `list[MyEnum]`
        EnumListOption(..., enum_type=MyEnum)
        EnumListOption(..., default=[MyEnum.Value])
        EnumListOption(..., enum_type=MyEnum default=lambda cls: cls.default)
    """

    @overload  # Case: static default
    def __new__(
        cls,
        *flag_names: str,
        default: list[_EnumT],
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = ...,
        daemon: bool | None = ...,
        default_help_repr: str | None = ...,
        fingerprint: bool | None = ...,
        fromfile: bool | None = ...,
        metavar: str | None = ...,
        mutually_exclusive_group: str | None = ...,
        removal_hint: str | None = ...,
        removal_version: str | None = ...,
    ) -> EnumListOption[_EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: dynamic default
    def __new__(
        cls,
        *flag_names: str,
        enum_type: type[_EnumT],
        default: _DynamicDefaultT,
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = ...,
        daemon: bool | None = ...,
        default_help_repr: str | None = ...,
        fingerprint: bool | None = ...,
        fromfile: bool | None = ...,
        metavar: str | None = ...,
        mutually_exclusive_group: str | None = ...,
        removal_hint: str | None = ...,
        removal_version: str | None = ...,
    ) -> EnumListOption[_EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: implicit default
    def __new__(
        cls,
        *flag_names: str,
        enum_type: type[_EnumT],
        help: _HelpT,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        # Additional bells/whistles
        advanced: bool | None = ...,
        daemon: bool | None = ...,
        default_help_repr: str | None = ...,
        fingerprint: bool | None = ...,
        fromfile: bool | None = ...,
        metavar: str | None = ...,
        mutually_exclusive_group: str | None = ...,
        removal_hint: str | None = ...,
        removal_version: str | None = ...,
    ) -> EnumListOption[_EnumT]:
        ...

    def __new__(
        cls,
        *flag_names,
        enum_type=None,
        default=[],
        help,
        register_if=None,
        # Additional bells/whistles
        advanced=None,
        daemon=None,
        default_help_repr=None,
        fingerprint=None,
        fromfile=None,
        metavar=None,
        mutually_exclusive_group=None,
        removal_hint=None,
        removal_version=None,
    ):
        instance = super().__new__(
            cls,
            *flag_names,
            default=default,
            help=help,
            register_if=register_if,
            advanced=advanced,
            daemon=daemon,
            default_help_repr=default_help_repr,
            fingerprint=fingerprint,
            fromfile=fromfile,
            metavar=metavar,
            mutually_exclusive_group=mutually_exclusive_group,
            removal_hint=removal_hint,
            removal_version=removal_version,
        )
        instance._enum_type = enum_type
        return instance

    def get_member_type(self, subsystem_cls):
        enum_type = self._enum_type
        default = _eval_maybe_dynamic(self._default, subsystem_cls)
        if enum_type is None:
            if not default:
                raise ValueError(
                    "`enum_type` must be provided to the constructor if `default` isn't provided "
                    "or is empty."
                )
            return type(default[0])
        return enum_type


# -----------------------------------------------------------------------------------------------
# Dict Concrete Option Classes
# -----------------------------------------------------------------------------------------------
_ValueT = TypeVar("_ValueT")


class DictOption(_OptionBase["dict[str, _ValueT]", "dict[str, _ValueT]"], Generic[_ValueT]):
    """A dictionary option mapping strings to client-provided `_ValueT`.

    If you provide a `default` parameter, the `_ValueT` type parameter will be inferred from the
    type of the values in the default. Otherwise, you'll need to provide `_ValueT` if you want a
    non-`Any` type.

    E.g.
        # Explicit
        DictOption[str](...)  # property type is `dict[str, str]`
        DictOption[Any](..., default=dict(key="val"))  # property type is `dict[str, Any]`
        # Implicit
        DictOption(...)  # property type is `dict[str, Any]`
        DictOption(..., default={"key": "val"})  # property type is `dict[str, str]`
        DictOption(..., default={"key": 1})  # property type is `dict[str, int]`
        DictOption(..., default={"key1": 1, "key2": "str"})  # property type is `dict[str, Any]`

    NOTE: The property returns a mutable object. Care should be used to not mutate the object.
    NOTE: Dictionary values are simply returned as parsed, and are not guaranteed to be of the
    `_ValueT` specified.
    """

    option_type: Any = dict

    def __new__(
        cls,
        *flag_names,
        default: _MaybeDynamicT[dict[str, _ValueT]] = {},
        help,
        register_if: Callable[[_SubsystemType], bool] | None = None,
        advanced: bool | None = None,
        daemon: bool | None = None,
        default_help_repr: str | None = None,
        fingerprint: bool | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_hint: str | None = None,
        removal_version: str | None = None,
    ):
        return super().__new__(
            cls,  # type: ignore[arg-type]
            *flag_names,
            default=default,  # type: ignore[arg-type]
            help=help,
            register_if=register_if,
            advanced=advanced,
            daemon=daemon,
            default_help_repr=default_help_repr,
            fingerprint=fingerprint,
            fromfile=fromfile,
            metavar=metavar,
            mutually_exclusive_group=mutually_exclusive_group,
            removal_hint=removal_hint,
            removal_version=removal_version,
        )

    def _convert_(self, val: Any) -> dict[str, _ValueT]:
        return cast("dict[str, _ValueT]", val)


# -----------------------------------------------------------------------------------------------
# "Specialized" Concrete Option Classes
# -----------------------------------------------------------------------------------------------


class SkipOption(BoolOption[bool]):
    """A --skip option (for an invocable tool)."""

    def __new__(cls, goal: str, *other_goals: str):
        goals = (goal,) + other_goals
        invocation_str = " and ".join([f"`{bin_name()} {goal}`" for goal in goals])
        return super().__new__(
            cls,  # type: ignore[arg-type]
            "--skip",
            default=False,  # type: ignore[arg-type]
            help=(
                lambda subsystem_cls: (
                    f"Don't use {subsystem_cls.name} when running {invocation_str}."
                )
            ),
        )


class ArgsListOption(ShellStrListOption):
    """An option for arguments passed to some other tool."""

    def __new__(
        cls,
        *,
        example: str,
        extra_help: str = "",
        tool_name: str | None = None,
        # This should be set when callers can alternatively use "--" followed by the arguments,
        # instead of having to provide "--[scope]-args='--arg1 --arg2'".
        passthrough: bool | None = None,
    ):
        if extra_help:
            extra_help = "\n\n" + extra_help
        instance = super().__new__(
            cls,  # type: ignore[arg-type]
            "--args",
            help=(
                lambda subsystem_cls: (
                    f"Arguments to pass directly to {tool_name or subsystem_cls.name}, "
                    f"e.g. `--{subsystem_cls.options_scope}-args='{example}'`.{extra_help}"
                )
            ),
        )
        if passthrough is not None:
            instance._extra_kwargs["passthrough"] = passthrough
        return instance
