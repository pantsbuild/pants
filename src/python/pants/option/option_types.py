# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Generic, Iterator, TypeVar, Union, cast, overload

from pants.option import custom_types
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class OptionsInfo:
    flag_names: tuple[str, ...]
    flag_options: dict[str, Any]


def collect_options_info(cls: type) -> Iterator[OptionsInfo]:
    """Yields the ordered options info from the MRO of the provided class."""

    # NB: Since registration ordering matters (it impacts `help` output), we register these in
    # class attribute order, starting from the base class down.
    for class_ in reversed(inspect.getmro(cls)):
        for attrname in class_.__dict__.keys():
            # NB: We use attrname and getattr to trigger descriptors
            attr = getattr(cls, attrname)
            if isinstance(attr, OptionsInfo):
                yield attr


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
# NB: Ideally this would be `Callable[[_SubsystemType], bool]`, however where this type is used is
# generally provided untyped lambdas.
_RegisterIfFuncT = Callable[[_SubsystemType], Any]


def _eval_maybe_dynamic(val: _MaybeDynamicT[_DefaultT], subsystem_cls: _SubsystemType) -> _DefaultT:
    return val(subsystem_cls) if inspect.isfunction(val) else val  # type: ignore[no-any-return]


class _OptionBase(Generic[_OptT, _DefaultT]):
    """Descriptor base for subsystem options.

    Clients shouldn't use this class directly, instead use one of the concrete classes below.

    This class serves two purposes:
        - Collect registration values for your option.
        - Provide a typed property for Python usage
    """

    _flag_names: tuple[str, ...] | None
    _default: _MaybeDynamicT[_DefaultT]
    _help: _HelpT
    _register_if: _RegisterIfFuncT
    _extra_kwargs: dict[str, Any]

    # NB: We define `__new__` rather than `__init__` because some subclasses need to define
    # `__new__` and mypy has issues if your class defines both.
    def __new__(
        cls,
        flag_name: str | None = None,
        *,
        default: _MaybeDynamicT[_DefaultT],
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ):
        """Construct a new Option descriptor.

        :param flag_name: The argument name, starting with "--", e.g. "--skip". Defaults to the class
            attribute name in kebab-case (without leading underscore).
        :param default: The default value the property will return if unspecified by the user. Note
            that for "scalar" option types (like StrOption and IntOption) this can either be an
            instance of the scalar type or `None`, but __must__ be provided.
            For Non-scalar types (like ListOption subclasses or DictOption) the default can't be
            `None`, but does have an "empty" default value.
        :param help: The help message to use when users run `pants help` or
            `pants help-advanced`
        :param register_if: A callable (usually a lambda) which, if provided, can be used to
            specify if the option should be registered. This is useful for "Base" subsystem
            classes, who might/might not want to register options based on information provided
            by the subclass. The callable takes one parameter: the derived subsystem class.
        :param advanced: If True, this option will only show up in `help-advanced`, and not
            `help`. You should generally set this value if the option will primarily be used by
            codebase administrators, such as setting up a config file.
        :param default_help_repr: The string representation of the option's default value.
            Useful when the default value doesn't have semantic meaning to the user.
            (E.g. If the default is set to the number of cores, `default_help_repr` might be set
            to "#cores")
        :param fromfile: If True, allows the user to specify a string value (starting with "@")
            which represents a file to read the option's value from.
        :param metavar: Sets what users see in `pants help` as possible values for the flag.
            The default is based on the option type (E.g. "<str>" or "<int>").
        :param mutually_exclusive_group: If specified disallows all other options using the same
            value to also be specified by the user.
        :param removal_version: If the option is deprecated, sets the version this option will
            be removed in. You must also set `removal_hint`.
        :param removal_hint: If the option is deprecated, provides a message to display to the
            user when running `help`.
        :param deprecation_start_version: If the option is deprecated, sets the version at which the
            deprecation will begin. Must be less than the `removal_version`.
        """
        self = super().__new__(cls)
        self._flag_names = (flag_name,) if flag_name else None
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
                "deprecation_start_version": deprecation_start_version,
            }.items()
            if v is not None
        }
        return self

    def __set_name__(self, owner, name) -> None:
        if self._flag_names is None:
            kebab_name = name.strip("_").replace("_", "-")
            self._flag_names = (f"--{kebab_name}",)

    # Subclasses can override if necessary
    def get_option_type(self, subsystem_cls):
        return type(self).option_type

    # Subclasses can override if necessary
    def _convert_(self, val: Any) -> _OptT:
        return cast("_OptT", val)

    def get_flag_options(self, subsystem_cls) -> dict:
        rh = "removal_hint"
        if rh in self._extra_kwargs:
            extra_kwargs: dict[str, Any] = {
                **self._extra_kwargs,
                rh: _eval_maybe_dynamic(self._extra_kwargs[rh], subsystem_cls),
            }
        else:
            extra_kwargs = self._extra_kwargs
        return dict(
            help=_eval_maybe_dynamic(self._help, subsystem_cls),
            default=_eval_maybe_dynamic(self._default, subsystem_cls),
            type=self.get_option_type(subsystem_cls),
            **extra_kwargs,
        )

    @overload
    def __get__(self, obj: None, objtype: Any) -> OptionsInfo | None:
        ...

    @overload
    def __get__(self, obj: object, objtype: Any) -> _OptT | _DefaultT:
        ...

    def __get__(self, obj, objtype):
        assert self._flag_names is not None
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
    """Descriptor base for a subsystem option of an homogenous list of some type.

    Don't use this class directly, instead use one of the concrete classes below.

    The default value will always be set as an empty list, and the Python property always returns
    a tuple (for immutability).
    """

    option_type = list

    def __new__(
        cls,
        flag_name: str | None = None,
        *,
        default: _MaybeDynamicT[list[_ListMemberT]] | None = [],
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ):
        default = default or []
        instance = super().__new__(
            cls,  # type: ignore[arg-type]
            flag_name,
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
            deprecation_start_version=deprecation_start_version,
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


class IntOrStrOption(_OptionBase[Union[str, int], _StrDefault]):
    """An option which takes either an integer or an open or closed set of strings."""

    def __new__(cls, *args, allowed_string_values: list[str] | None = None, **kwargs):
        instance = super().__new__(
            cls,  # type: ignore[arg-type]
            *args,
            **kwargs,
        )

        instance.allowed_string_values = allowed_string_values

        class _OptionType:
            def __init__(self, value: str | int) -> None:
                self._allowed_string_values = allowed_string_values
                if not isinstance(value, str) and not isinstance(value, int):
                    raise ValueError(
                        f"Expected an int or a string, got {type(value)} with value {value}"
                    )
                if isinstance(value, str):
                    try:
                        value = int(value)
                    except ValueError:
                        if allowed_string_values is not None and value not in allowed_string_values:
                            raise ValueError(
                                f"Expected an integer or a string from {{{', '.join(allowed_string_values)}}}, got '{value}'"
                            )

                self.value = value

            def __repr__(self):
                return f"IntOrStrOption<{{{', '.join(allowed_string_values)}}}>(value={self.value})"

            def __eq__(self, other):
                return (
                    self.value == other.value
                    and self._allowed_string_values == other._allowed_string_values
                )

        instance.option_type = _OptionType

        return instance

    def get_option_type(self, subsystem_cls):
        return self.option_type

    allowed_string_values: list[str] | None = None


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
        inferred from the type of the default.
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
        flag_name: str | None = None,
        *,
        default: _EnumT,
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ) -> EnumOption[_EnumT, _EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: dynamic default
    def __new__(
        cls,
        flag_name: str | None = None,
        *,
        enum_type: type[_EnumT],
        default: _DynamicDefaultT,
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ) -> EnumOption[_EnumT, _EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: default is `None`
    def __new__(
        cls,
        flag_name: str | None = None,
        *,
        enum_type: type[_EnumT],
        default: None,
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ) -> EnumOption[_EnumT, None]:
        ...

    def __new__(
        cls,
        flag_name=None,
        *,
        enum_type=None,
        default,
        help,
        # Additional bells/whistles
        register_if=None,
        advanced=None,
        default_help_repr=None,
        fromfile=None,
        metavar=None,
        mutually_exclusive_group=None,
        removal_version=None,
        removal_hint=None,
        deprecation_start_version=None,
        # Internal bells/whistles
        daemon=None,
        fingerprint=None,
    ):
        instance = super().__new__(
            cls,
            flag_name,
            default=default,
            help=help,
            register_if=register_if,
            advanced=advanced,
            default_help_repr=default_help_repr,
            fromfile=fromfile,
            metavar=metavar,
            mutually_exclusive_group=mutually_exclusive_group,
            removal_version=removal_version,
            removal_hint=removal_hint,
            deprecation_start_version=deprecation_start_version,
            daemon=daemon,
            fingerprint=fingerprint,
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
        flag_name: str | None = None,
        *,
        default: list[_EnumT],
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ) -> EnumListOption[_EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: dynamic default
    def __new__(
        cls,
        flag_name: str | None = None,
        *,
        enum_type: type[_EnumT],
        default: _DynamicDefaultT,
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ) -> EnumListOption[_EnumT]:
        ...

    # N.B. This has an additional param: `enum_type`.
    @overload  # Case: implicit default
    def __new__(
        cls,
        flag_name: str | None = None,
        *,
        enum_type: type[_EnumT],
        help: _HelpT,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ) -> EnumListOption[_EnumT]:
        ...

    def __new__(
        cls,
        flag_name=None,
        *,
        enum_type=None,
        default=[],
        help,
        # Additional bells/whistles
        register_if=None,
        advanced=None,
        default_help_repr=None,
        fromfile=None,
        metavar=None,
        mutually_exclusive_group=None,
        removal_version=None,
        removal_hint=None,
        deprecation_start_version=None,
        # Internal bells/whistles
        daemon=None,
        fingerprint=None,
    ):
        instance = super().__new__(
            cls,
            flag_name,
            default=default,
            help=help,
            register_if=register_if,
            advanced=advanced,
            default_help_repr=default_help_repr,
            fromfile=fromfile,
            metavar=metavar,
            mutually_exclusive_group=mutually_exclusive_group,
            removal_version=removal_version,
            removal_hint=removal_hint,
            deprecation_start_version=deprecation_start_version,
            daemon=daemon,
            fingerprint=fingerprint,
        )
        instance._enum_type = enum_type
        return instance

    def get_member_type(self, subsystem_cls):
        enum_type = self._enum_type
        default = _eval_maybe_dynamic(self._default, subsystem_cls)
        if enum_type is None:
            if not default:
                raise ValueError(
                    softwrap(
                        """
                        `enum_type` must be provided to the constructor if `default` isn't provided
                        or is empty.
                        """
                    )
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
        flag_name: str | None = None,
        *,
        default: _MaybeDynamicT[dict[str, _ValueT]] = {},
        help,
        # Additional bells/whistles
        register_if: _RegisterIfFuncT | None = None,
        advanced: bool | None = None,
        default_help_repr: str | None = None,
        fromfile: bool | None = None,
        metavar: str | None = None,
        mutually_exclusive_group: str | None = None,
        removal_version: str | None = None,
        removal_hint: _HelpT | None = None,
        deprecation_start_version: str | None = None,
        # Internal bells/whistles
        daemon: bool | None = None,
        fingerprint: bool | None = None,
    ):
        return super().__new__(
            cls,  # type: ignore[arg-type]
            flag_name,
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
            deprecation_start_version=deprecation_start_version,
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
            default=False,  # type: ignore[arg-type]
            help=lambda subsystem_cls: (
                f"If true, don't use {subsystem_cls.name} when running {invocation_str}."
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
        default: _MaybeDynamicT[list[_ListMemberT]] | None = None,
    ):
        if extra_help:
            extra_help = "\n\n" + extra_help
        instance = super().__new__(
            cls,  # type: ignore[arg-type]
            help=(
                lambda subsystem_cls: softwrap(
                    f"""
                    Arguments to pass directly to {tool_name or subsystem_cls.name},
                    e.g. `--{subsystem_cls.options_scope}-args='{example}'`.{extra_help}
                    """
                )
            ),
            default=default,  # type: ignore[arg-type]
        )
        if passthrough is not None:
            instance._extra_kwargs["passthrough"] = passthrough
        return instance
