# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.option.scope import GLOBAL_SCOPE


class OptionsError(Exception):
    """An options system-related error."""


# -----------------------------------------------------------------------
# Option registration errors
# -----------------------------------------------------------------------


class RegistrationError(OptionsError):
    """An error at option registration time."""

    def __init__(self, scope: str, option: str, **msg_format_args) -> None:
        scope_str = "global scope" if scope == GLOBAL_SCOPE else f"scope {scope}"
        if self.__doc__ is None:
            raise ValueError(
                "Invalid RegistrationError definition. "
                "Please specify the error message in the docstring."
            )
        docstring = self.__doc__.format(**msg_format_args)
        super().__init__(f"{docstring} [option {option} in {scope_str}].")


class BooleanOptionNameWithNo(RegistrationError):
    """Boolean option names cannot start with --no."""


class DefaultValueType(RegistrationError):
    """Default value {value_type}({default_value!r}) does not match option type {option_type}."""


class DefaultMemberValueType(DefaultValueType):
    """Default member value type mismatch.

    Member value {value_type}({member_value!r}) does not match list option type {member_type}.
    """


class ImplicitValIsNone(RegistrationError):
    """Implicit value cannot be None."""


class InvalidKwarg(RegistrationError):
    """Invalid registration kwarg {kwarg}."""


class InvalidKwargNonGlobalScope(RegistrationError):
    """Invalid registration kwarg {kwarg} on non-global scope."""


class InvalidMemberType(RegistrationError):
    """member_type {member_type} not allowed."""


class MemberTypeNotAllowed(RegistrationError):
    """member_type not allowed on option with type {type_}.

    It may only be specified if type=list.
    """


class NoOptionNames(RegistrationError):
    """No option names provided."""


class OptionAlreadyRegistered(RegistrationError):
    """An option with this name was already registered on this scope."""


class OptionNameDash(RegistrationError):
    """Option name must begin with a dash."""


class OptionNameDoubleDash(RegistrationError):
    """Long option name must begin with a double-dash."""


class PassthroughType(RegistrationError):
    """Options marked passthrough must be typed as a string list."""


# -----------------------------------------------------------------------
# Flag parsing errors
# -----------------------------------------------------------------------


class ParseError(OptionsError):
    """An error at flag parsing time."""


class BooleanConversionError(ParseError):
    """Indicates a value other than 'True' or 'False' when attempting to parse a bool."""


class FromfileError(ParseError):
    """Indicates a problem reading a value @fromfile."""


class MutuallyExclusiveOptionError(ParseError):
    """Indicates that two options in the same mutually exclusive group were specified."""


class UnknownFlagsError(ParseError):
    """Indicates that unknown command-line flags were encountered in some scope."""

    def __init__(self, flags: Tuple[str, ...], arg_scope: str):
        self.flags = flags
        self.arg_scope = arg_scope
        scope = f"scope {self.arg_scope}" if self.arg_scope else "global scope"
        msg = f"Unknown flags {', '.join(self.flags)} on {scope}"
        super().__init__(msg)
