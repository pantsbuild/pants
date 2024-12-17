# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import copy
import inspect
import logging
import typing
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Mapping

from pants.base.deprecated import validate_deprecation_semver
from pants.option.custom_types import (
    DictValueComponent,
    ListValueComponent,
    UnsetBool,
    dir_option,
    file_option,
    shell_str,
    target_option,
)
from pants.option.errors import (
    BooleanConversionError,
    DefaultMemberValueType,
    DefaultValueType,
    HelpType,
    InvalidKwarg,
    InvalidKwargNonGlobalScope,
    InvalidMemberType,
    MemberTypeNotAllowed,
    NoOptionNames,
    OptionAlreadyRegistered,
    OptionNameDoubleDash,
    ParseError,
    PassthroughType,
    RegistrationError,
)
from pants.option.native_options import parse_dest
from pants.option.option_types import OptionInfo
from pants.option.ranked_value import RankedValue
from pants.option.scope import GLOBAL_SCOPE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptionValueHistory:
    ranked_values: tuple[RankedValue, ...]

    @property
    def final_value(self) -> RankedValue:
        return self.ranked_values[-1]


class OptionRegistrar:
    """Holds information about registered options."""

    @staticmethod
    def is_bool(kwargs: Mapping[str, Any]) -> bool:
        type_arg = kwargs.get("type")
        if type_arg is None:
            return False
        if type_arg is bool:
            return True
        try:
            return typing.get_type_hints(type_arg).get("return") is bool
        except TypeError:
            return False

    @staticmethod
    def ensure_bool(val: bool | str) -> bool:
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            s = val.lower()
            if s == "true":
                return True
            if s == "false":
                return False
            raise BooleanConversionError(f'Got "{val}". Expected "True" or "False".')
        raise BooleanConversionError(f"Got {val}. Expected True or False.")

    @classmethod
    def _invert(cls, s: bool | str | None) -> bool | None:
        if s is None:
            return None
        b = cls.ensure_bool(s)
        return not b

    def __init__(self, scope: str) -> None:
        """Create an OptionRegistrar instance.

        :param scope: the scope this registrar acts for.
        """
        self._scope = scope

        # All option args registered with this registrar.  Used to prevent conflicts.
        self._known_args: set[str] = set()

        # List of (args, kwargs) registration pairs, exactly as captured at registration time.
        self._option_registrations: list[tuple[tuple[str, ...], dict[str, Any]]] = []

        # Map of dest -> history.
        self._history: dict[str, OptionValueHistory] = {}

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def known_scoped_args(self) -> frozenset[str]:
        prefix = f"{self.scope}-" if self.scope != GLOBAL_SCOPE else ""
        return frozenset(f"--{prefix}{arg.lstrip('--')}" for arg in self._known_args)

    def option_registrations_iter(self) -> Iterator[OptionInfo]:
        """Returns an iterator over the normalized registration arguments of each option in this
        registrar.

        Useful for generating help and other documentation.

        Each yielded item is an OptionInfo containing the args and kwargs as passed to register(),
        except that kwargs will be normalized to always have 'dest' and 'default' explicitly set.
        """

        def normalize_kwargs(orig_args, orig_kwargs):
            nkwargs = copy.copy(orig_kwargs)
            dest = parse_dest(OptionInfo(orig_args, nkwargs))
            nkwargs["dest"] = dest
            if "default" not in nkwargs:
                type_arg = nkwargs.get("type", str)
                member_type = nkwargs.get("member_type", str)
                default_val = self.to_value_type(nkwargs.get("default"), type_arg, member_type)
                if isinstance(default_val, (ListValueComponent, DictValueComponent)):
                    default_val = default_val.val
                nkwargs["default"] = default_val
            return nkwargs

        # Yield our directly-registered options.
        for args, kwargs in self._option_registrations:
            normalized_kwargs = normalize_kwargs(args, kwargs)
            yield OptionInfo(args, normalized_kwargs)

    def register(self, *args, **kwargs) -> None:
        """Register an option."""
        self._validate(args, kwargs)

        if self.is_bool(kwargs):
            default = kwargs.get("default")
            if default is None:
                # Unless a tri-state bool is explicitly opted into with the `UnsetBool` default value,
                # boolean options always have an implicit default of False. We make that explicit here.
                kwargs["default"] = False
            elif default is UnsetBool:
                kwargs["default"] = None

        # Record the args. We'll do the underlying parsing on-demand.
        self._option_registrations.append((args, kwargs))

        # Look for direct conflicts.
        for arg in args:
            if arg in self._known_args:
                raise OptionAlreadyRegistered(self.scope, arg)
        self._known_args.update(args)

    _allowed_registration_kwargs = {
        "type",
        "member_type",
        "choices",
        "dest",
        "default",
        "default_help_repr",
        "metavar",
        "help",
        "advanced",
        "fingerprint",
        "removal_version",
        "removal_hint",
        "deprecation_start_version",
        "fromfile",
        "mutually_exclusive_group",
        "daemon",
        "passthrough",
        "environment_aware",
    }

    _allowed_member_types = {
        str,
        int,
        float,
        dict,
        dir_option,
        file_option,
        target_option,
        shell_str,
    }

    def _validate(self, args, kwargs) -> None:
        """Validate option registration arguments."""

        def error(
            exception_type: type[RegistrationError],
            arg_name: str | None = None,
            **msg_kwargs,
        ) -> None:
            if arg_name is None:
                arg_name = args[0] if args else "<unknown>"
            raise exception_type(self.scope, arg_name, **msg_kwargs)

        if not args:
            error(NoOptionNames)
        # Validate args.
        for arg in args:
            # We ban short args like `-x`, except for special casing the global option `-l`.
            if not arg.startswith("--") and not (self.scope == GLOBAL_SCOPE and arg == "-l"):
                error(OptionNameDoubleDash, arg_name=arg)

        # Validate kwargs.
        type_arg = kwargs.get("type", str)
        if "member_type" in kwargs and type_arg != list:
            error(MemberTypeNotAllowed, type_=type_arg.__name__)
        member_type = kwargs.get("member_type", str)
        is_enum = inspect.isclass(member_type) and issubclass(member_type, Enum)
        if not is_enum and member_type not in self._allowed_member_types:
            error(InvalidMemberType, member_type=member_type.__name__)

        help_arg = kwargs.get("help")
        if help_arg is not None and not isinstance(help_arg, str):
            error(HelpType, help_type=type(help_arg).__name__)

        # check type of default value
        default_value = kwargs.get("default")
        if default_value is not None:
            if isinstance(default_value, str) and type_arg != str:
                # attempt to parse default value, for correctness.
                # custom function types may implement their own validation
                default_value = self.to_value_type(default_value, type_arg, member_type)
                if hasattr(default_value, "val"):
                    default_value = default_value.val

                # fall through to type check, to verify that custom types returned a value of correct type

            if (
                isinstance(type_arg, type)
                and not isinstance(default_value, type_arg)
                and not (issubclass(type_arg, bool) and default_value == UnsetBool)
            ):
                error(
                    DefaultValueType,
                    option_type=type_arg.__name__,
                    default_value=kwargs["default"],
                    value_type=type(default_value).__name__,
                )

            # verify list member types (this is not done by the custom list value type)
            if type_arg == list:
                for member_val in default_value:
                    if not isinstance(member_type, type):
                        # defer value validation to custom type
                        member_type(member_val)

                    elif not isinstance(member_val, member_type):
                        error(
                            DefaultMemberValueType,
                            member_type=member_type.__name__,
                            member_value=member_val,
                            value_type=type(member_val).__name__,
                        )

        if (
            "passthrough" in kwargs
            and kwargs["passthrough"]
            and (type_arg != list or member_type not in (shell_str, str))
        ):
            error(PassthroughType)

        for kwarg in kwargs:
            if kwarg not in self._allowed_registration_kwargs:
                error(InvalidKwarg, kwarg=kwarg)

            # Ensure `daemon=True` can't be passed on non-global scopes.
            if kwarg == "daemon" and self.scope != GLOBAL_SCOPE:
                error(InvalidKwargNonGlobalScope, kwarg=kwarg)

        removal_version = kwargs.get("removal_version")
        if removal_version is not None:
            validate_deprecation_semver(removal_version, "removal version")

    @classmethod
    def to_value_type(cls, val_str, type_arg, member_type):
        """Convert a string to a value of the option's type."""
        if val_str is None:
            return None
        if type_arg == bool:
            return cls.ensure_bool(val_str)
        try:
            if type_arg == list:
                return ListValueComponent.create(val_str, member_type=member_type)
            if type_arg == dict:
                return DictValueComponent.create(val_str)
            return type_arg(val_str)
        except (TypeError, ValueError) as e:
            if issubclass(type_arg, Enum):
                choices = ", ".join(f"{choice.value}" for choice in type_arg)
                raise ParseError(f"Invalid choice '{val_str}'. Choose from: {choices}")
            raise ParseError(
                f"Error applying type '{type_arg.__name__}' to option value '{val_str}': {e}"
            )

    def __str__(self) -> str:
        return f"OptionRegistrar({self.scope})"
