# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Iterable, Mapping, Sequence

from pants.base.exceptions import MappingError
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import (  # noqa: F401
    AddressParseException as AddressParseException,
)
from pants.util.dirutil import fast_relpath, longest_dir_prefix
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init
from pants.util.strutil import bullet_list, softwrap, strip_prefix

# `:`, `#`, `@` are used as delimiters already. Others are reserved for possible future needs.
BANNED_CHARS_IN_TARGET_NAME = frozenset(r":#!@?/\=")
BANNED_CHARS_IN_GENERATED_NAME = frozenset(r":#!@?=")
BANNED_CHARS_IN_PARAMETERS = frozenset(r":#!@?=, ")


class InvalidAddressError(AddressParseException):
    pass


class InvalidSpecPathError(InvalidAddressError):
    """Indicate an invalid spec path for `Address`."""


class InvalidTargetNameError(InvalidAddressError):
    """Indicate an invalid target name for `Address`."""


class InvalidParametersError(InvalidAddressError):
    """Indicate invalid parameter values for `Address`."""


class UnsupportedWildcardError(InvalidAddressError):
    """Indicate that an address wildcard was used."""


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressInput:
    """A string that has been parsed and normalized using the Address syntax.

    An AddressInput must be resolved into an Address using the engine (which involves inspecting
    disk to determine the types of its path component).
    """

    path_component: str
    target_component: str | None
    generated_component: str | None
    parameters: FrozenDict[str, str]
    description_of_origin: str

    def __init__(
        self,
        path_component: str,
        target_component: str | None = None,
        *,
        generated_component: str | None = None,
        parameters: Mapping[str, str] = FrozenDict(),
        description_of_origin: str,
    ) -> None:
        self.path_component = path_component
        self.target_component = target_component
        self.generated_component = generated_component
        self.parameters = FrozenDict(parameters)
        self.description_of_origin = description_of_origin

        if not self.target_component:
            if self.target_component is not None:
                raise InvalidTargetNameError(
                    softwrap(
                        f"""
                        Address `{self.spec}` from {self.description_of_origin} sets
                        the name component to the empty string, which is not legal.
                        """
                    )
                )
            if self.path_component == "":
                raise InvalidTargetNameError(
                    softwrap(
                        f"""
                        Address `{self.spec}` from {self.description_of_origin} has no name part,
                        but it's necessary because the path is the build root.
                        """
                    )
                )

        if self.path_component != "":
            if os.path.isabs(self.path_component):
                raise InvalidSpecPathError(
                    softwrap(
                        f"""
                        Invalid address {self.spec} from {self.description_of_origin}. Cannot use
                        absolute paths.
                        """
                    )
                )

            invalid_component = next(
                (
                    component
                    for component in self.path_component.split(os.sep)
                    if component in (".", "..", "")
                ),
                None,
            )
            if invalid_component is not None:
                raise InvalidSpecPathError(
                    softwrap(
                        f"""
                        Invalid address `{self.spec}` from {self.description_of_origin}. It has an
                        un-normalized path part: '{os.sep}{invalid_component}'.
                        """
                    )
                )

        for k, v in self.parameters.items():
            key_banned = set(BANNED_CHARS_IN_PARAMETERS & set(k))
            if key_banned:
                raise InvalidParametersError(
                    softwrap(
                        f"""
                        Invalid address `{self.spec}` from {self.description_of_origin}. It has
                        illegal characters in parameter keys: `{key_banned}` in `{k}={v}`.
                        """
                    )
                )
            val_banned = set(BANNED_CHARS_IN_PARAMETERS & set(v))
            if val_banned:
                raise InvalidParametersError(
                    softwrap(
                        f"""
                        Invalid address `{self.spec}` from {self.description_of_origin}. It has
                        illegal characters in parameter values: `{val_banned}` in `{k}={v}`.
                        """
                    )
                )

    @classmethod
    def parse(
        cls,
        spec: str,
        *,
        relative_to: str | None = None,
        subproject_roots: Sequence[str] | None = None,
        description_of_origin: str,
    ) -> AddressInput:
        """Parse a string into an AddressInput.

        :param spec: Target address spec.
        :param relative_to: path to use for sibling specs, ie: ':another_in_same_build_family',
          interprets the missing spec_path part as `relative_to`.
        :param subproject_roots: Paths that correspond with embedded build roots under
          the current build root.
        :param description_of_origin: where the AddressInput comes from, e.g. "CLI arguments" or
          "the option `--paths-from`". This is used for better error messages.

        For example:

            some_target(
                name='mytarget',
                dependencies=['path/to/buildfile:targetname'],
            )

        Where `path/to/buildfile:targetname` is the dependent target address spec.

        In there is no target name component, it defaults the default target in the resulting
        Address's spec_path.

        Optionally, specs can be prefixed with '//' to denote an absolute spec path. This is
        normally not significant except when a spec referring to a root level target is needed
        from deeper in the tree. For example, in `path/to/buildfile/BUILD`:

            some_target(
                name='mytarget',
                dependencies=[':targetname'],
            )

        The `targetname` spec refers to a target defined in `path/to/buildfile/BUILD*`. If instead
        you want to reference `targetname` in a root level BUILD file, use the absolute form.
        For example:

            some_target(
                name='mytarget',
                dependencies=['//:targetname'],
            )

        The spec may be for a generated target: `dir:generator#generated`.

        The spec may be a file, such as `a/b/c.txt`. It may include a relative address spec at the
        end, such as `a/b/c.txt:original` or `a/b/c.txt:../original`, to disambiguate which target
        the file comes from; otherwise, it will be assumed to come from the default target in the
        directory, i.e. a target which leaves off `name`.
        """
        subproject = (
            longest_dir_prefix(relative_to, subproject_roots)
            if relative_to and subproject_roots
            else None
        )

        def prefix_subproject(spec_path: str) -> str:
            if not subproject:
                return spec_path
            if spec_path:
                return os.path.join(subproject, spec_path)
            return os.path.normpath(subproject)

        (
            (
                path_component,
                target_component,
                generated_component,
                parameters,
            ),
            wildcard,
        ) = native_engine.address_spec_parse(spec)

        if wildcard:
            raise UnsupportedWildcardError(
                softwrap(
                    f"""
                    The address `{spec}` from {description_of_origin} ended in a wildcard
                    (`{wildcard}`), which is not supported.
                    """
                )
            )

        normalized_relative_to = None
        if relative_to:
            normalized_relative_to = (
                fast_relpath(relative_to, subproject) if subproject else relative_to
            )
        if path_component.startswith("./") and normalized_relative_to:
            path_component = os.path.join(normalized_relative_to, path_component[2:])
        if not path_component and normalized_relative_to:
            path_component = normalized_relative_to

        path_component = prefix_subproject(strip_prefix(path_component, "//"))

        return cls(
            path_component,
            target_component,
            generated_component=generated_component,
            parameters=FrozenDict(sorted(parameters)),
            description_of_origin=description_of_origin,
        )

    def file_to_address(self) -> Address:
        """Converts to an Address by assuming that the path_component is a file on disk."""
        if self.target_component is None:
            # Use the default target in the same directory as the file.
            spec_path, relative_file_path = os.path.split(self.path_component)
            # We validate that this is not a top-level file. We couldn't do this earlier in the
            # AddressSpec constructor because we weren't sure if the path_spec referred to a file
            # vs. a directory.
            if not spec_path:
                raise InvalidTargetNameError(
                    softwrap(
                        f"""
                        Addresses for generated first-party targets in the build root must include
                        which target generator they come from, such as
                        `{self.path_component}:original_target`. However, `{self.spec}`
                        from {self.description_of_origin} did not have a target name.
                        """
                    )
                )
            return Address(
                spec_path=spec_path,
                relative_file_path=relative_file_path,
                parameters=self.parameters,
            )

        # The target component may be "above" (but not below) the file in the filesystem.
        # Determine how many levels above the file it is, and validate that the path is relative.
        parent_count = self.target_component.count(os.path.sep)
        if parent_count == 0:
            spec_path, relative_file_path = os.path.split(self.path_component)
            return Address(
                spec_path=spec_path,
                relative_file_path=relative_file_path,
                target_name=self.target_component,
                parameters=self.parameters,
            )

        expected_prefix = f"..{os.path.sep}" * parent_count
        if self.target_component[: self.target_component.rfind(os.path.sep) + 1] != expected_prefix:
            raise InvalidTargetNameError(
                softwrap(
                    f"""
                    Invalid address `{self.spec}` from {self.description_of_origin}. The target
                    name portion of the address must refer to a target defined in the same
                    directory or a parent directory of the file path `{self.path_component}`, but
                    the value `{self.target_component}` is a subdirectory.
                    """
                )
            )

        # Split the path_component into a spec_path and relative_file_path at the appropriate
        # position.
        path_components = self.path_component.split(os.path.sep)
        if len(path_components) <= parent_count:
            raise InvalidTargetNameError(
                softwrap(
                    f"""
                    Invalid address `{self.spec}` from {self.description_of_origin}. The target
                    name portion of the address `{self.target_component}` has too many `../`, which
                    means it refers to a directory above the file path `{self.path_component}`.
                    Expected no more than {len(path_components) -1 } instances of `../` in
                    `{self.target_component}`, but found {parent_count} instances.
                    """
                )
            )
        offset = -1 * (parent_count + 1)
        spec_path = os.path.join(*path_components[:offset]) if path_components[:offset] else ""
        relative_file_path = os.path.join(*path_components[offset:])
        target_name = os.path.basename(self.target_component)
        return Address(
            spec_path,
            relative_file_path=relative_file_path,
            target_name=target_name,
            parameters=self.parameters,
        )

    def dir_to_address(self) -> Address:
        """Converts to an Address by assuming that the path_component is a directory on disk."""
        return Address(
            spec_path=self.path_component,
            target_name=self.target_component,
            generated_name=self.generated_component,
            parameters=self.parameters,
        )

    @property
    def spec(self) -> str:
        rep = self.path_component or "//"
        if self.generated_component:
            rep += f"#{self.generated_component}"
        if self.target_component:
            rep += f":{self.target_component}"
        if self.parameters:
            params_vals = ",".join(f"{k}={v}" for k, v in self.parameters.items())
            rep += f"@{params_vals}"
        return rep


class Address(EngineAwareParameter):
    """The unique address for a `Target`.

    Targets explicitly declared in BUILD files use the format `path/to:tgt`, whereas targets
    generated from other targets use the format `path/to:generator#generated`.
    """

    def __init__(
        self,
        spec_path: str,
        *,
        target_name: str | None = None,
        parameters: Mapping[str, str] | None = None,
        generated_name: str | None = None,
        relative_file_path: str | None = None,
    ) -> None:
        """
        :param spec_path: The path from the build root to the directory containing the BUILD file
          for the target. If the target is generated, this is the path to the generator target.
        :param target_name: The name of the target. For generated targets, this is the name of
            its target generator. If the `name` is left off (i.e. the default), set to `None`.
        :param parameters: A series of key-value pairs which are incorporated into the identity of
            the Address.
        :param generated_name: The name of what is generated. You can use a file path if the
            generated target represents an entity from the file system, such as `a/b/c` or
            `subdir/f.ext`.
        :param relative_file_path: The relative path from the spec_path to an addressed file,
          if any. Because files must always be located below targets that apply metadata to
          them, this will always be relative.
        """
        self.spec_path = spec_path
        self.parameters = FrozenDict(parameters) if parameters else FrozenDict()
        self.generated_name = generated_name
        self._relative_file_path = relative_file_path
        if generated_name:
            if relative_file_path:
                raise AssertionError(
                    f"Do not use both `generated_name` ({generated_name}) and "
                    f"`relative_file_path` ({relative_file_path})."
                )
            banned_chars = BANNED_CHARS_IN_GENERATED_NAME & set(generated_name)
            if banned_chars:
                raise InvalidTargetNameError(
                    f"The generated name `{generated_name}` (defined in directory "
                    f"{self.spec_path}, the part after `#`) contains banned characters "
                    f"(`{'`,`'.join(banned_chars)}`). Please replace "
                    "these characters with another separator character like `_`, `-`, or `/`."
                )

        # If the target_name is the same as the default name would be, we normalize to None.
        self._target_name = None
        if target_name and target_name != os.path.basename(self.spec_path):
            banned_chars = BANNED_CHARS_IN_TARGET_NAME & set(target_name)
            if banned_chars:
                raise InvalidTargetNameError(
                    f"The target name {target_name} (defined in directory {self.spec_path}) "
                    f"contains banned characters (`{'`,`'.join(banned_chars)}`). Please replace "
                    "these characters with another separator character like `_` or `-`."
                )
            self._target_name = target_name

        self._hash = hash(
            (self.spec_path, self._target_name, self.generated_name, self._relative_file_path)
        )
        if PurePath(spec_path).name.startswith("BUILD"):
            raise InvalidSpecPathError(
                f"The address {self.spec} has {PurePath(spec_path).name} as the last part of its "
                f"path, but BUILD is a reserved name. Please make sure that you did not name any "
                f"directories BUILD."
            )

    @property
    def is_generated_target(self) -> bool:
        return self.generated_name is not None or self.is_file_target

    @property
    def is_file_target(self) -> bool:
        return self._relative_file_path is not None

    @property
    def is_parametrized(self) -> bool:
        return bool(self.parameters)

    def is_parametrized_subset_of(self, other: Address) -> bool:
        """True if this Address is == to the given Address, but with a subset of its parameters."""
        if not self._equal_without_parameters(other):
            return False
        return self.parameters.items() <= other.parameters.items()

    @property
    def filename(self) -> str:
        if self._relative_file_path is None:
            raise AssertionError(
                f"Only a file Address (`self.is_file_target`) has a filename: {self}"
            )
        return os.path.join(self.spec_path, self._relative_file_path)

    @property
    def target_name(self) -> str:
        if self._target_name is None:
            return os.path.basename(self.spec_path)
        return self._target_name

    @property
    def parameters_repr(self) -> str:
        if not self.parameters:
            return ""
        rhs = ",".join(f"{k}={v}" for k, v in self.parameters.items())
        return f"@{rhs}"

    @property
    def spec(self) -> str:
        """The canonical string representation of the Address.

        Prepends '//' if the target is at the root, to disambiguate build root level targets
        from "relative" spec notation.

        :API: public
        """
        prefix = "//" if not self.spec_path else ""
        if self._relative_file_path is None:
            path = self.spec_path
            target = (
                ""
                if self._target_name is None and (self.generated_name or self.parameters)
                else self.target_name
            )
        else:
            path = self.filename
            parent_prefix = "../" * self._relative_file_path.count(os.path.sep)
            target = (
                ""
                if self._target_name is None and not parent_prefix
                else f"{parent_prefix}{self.target_name}"
            )
        target_sep = ":" if target else ""
        generated = "" if self.generated_name is None else f"#{self.generated_name}"
        return f"{prefix}{path}{target_sep}{target}{generated}{self.parameters_repr}"

    @property
    def path_safe_spec(self) -> str:
        """
        :API: public
        """

        def sanitize(s: str) -> str:
            return s.replace(os.path.sep, ".")

        if self._relative_file_path:
            parent_count = self._relative_file_path.count(os.path.sep)
            parent_prefix = "@" * parent_count if parent_count else "."
            path = f".{sanitize(self._relative_file_path)}"
        else:
            parent_prefix = "."
            path = ""
        if parent_prefix == ".":
            target = f"{parent_prefix}{self._target_name}" if self._target_name else ""
        else:
            target = f"{parent_prefix}{self.target_name}"
        if self.parameters:
            params = f"@{sanitize(self.parameters_repr)}"
        else:
            params = ""
        generated = f"@{sanitize(self.generated_name)}" if self.generated_name else ""
        prefix = sanitize(self.spec_path)
        return f"{prefix}{path}{target}{generated}{params}"

    def parametrize(self, parameters: Mapping[str, str]) -> Address:
        """Creates a new Address with the given `parameters` merged over self.parameters."""
        merged_parameters = {**self.parameters, **parameters}
        return self.__class__(
            self.spec_path,
            target_name=self._target_name,
            generated_name=self.generated_name,
            relative_file_path=self._relative_file_path,
            parameters=merged_parameters,
        )

    def maybe_convert_to_target_generator(self) -> Address:
        """If this address is generated or parametrized, convert it to its generator target.

        Otherwise, return self unmodified.
        """
        if self.is_generated_target or self.is_parametrized:
            return self.__class__(self.spec_path, target_name=self._target_name)
        return self

    def create_generated(self, generated_name: str) -> Address:
        if self.is_generated_target:
            raise AssertionError(f"Cannot call `create_generated` on `{self}`.")
        return self.__class__(
            self.spec_path,
            target_name=self._target_name,
            parameters=self.parameters,
            generated_name=generated_name,
        )

    def create_file(self, relative_file_path: str) -> Address:
        if self.is_generated_target:
            raise AssertionError(f"Cannot call `create_file` on `{self}`.")
        return self.__class__(
            self.spec_path,
            target_name=self._target_name,
            parameters=self.parameters,
            relative_file_path=relative_file_path,
        )

    def _equal_without_parameters(self, other: Address) -> bool:
        return (
            self.spec_path == other.spec_path
            and self._target_name == other._target_name
            and self.generated_name == other.generated_name
            and self._relative_file_path == other._relative_file_path
        )

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, Address):
            return False
        return self._equal_without_parameters(other) and self.parameters == other.parameters

    def __hash__(self):
        return self._hash

    def __repr__(self) -> str:
        return f"Address({self.spec})"

    def __str__(self) -> str:
        return self.spec

    def __lt__(self, other):
        # NB: This ordering is intentional so that we match the spec format:
        # `{spec_path}{relative_file_path}:{tgt_name}#{generated_name}`.
        return (
            self.spec_path,
            self._relative_file_path or "",
            self._target_name or "",
            self.parameters,
            self.generated_name or "",
        ) < (
            other.spec_path,
            other._relative_file_path or "",
            other._target_name or "",
            self.parameters,
            other.generated_name or "",
        )

    def debug_hint(self) -> str:
        return self.spec

    def metadata(self) -> dict[str, Any]:
        return {"address": self.spec}


@dataclass(frozen=True)
class BuildFileAddressRequest(EngineAwareParameter):
    """A request to find the BUILD file path for an address."""

    address: Address
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class BuildFileAddress:
    """An address, along with the relative file path of its BUILD file."""

    address: Address
    rel_path: str


class ResolveError(MappingError):
    """Indicates an error resolving targets."""

    @classmethod
    def did_you_mean(
        cls,
        bad_address: Address,
        *,
        description_of_origin: str,
        known_names: Iterable[str],
        namespace: str,
    ) -> ResolveError:
        return cls(
            softwrap(
                f"""
                The address {bad_address} from {description_of_origin} does not exist.

                The target name ':{bad_address.target_name}' is not defined in the directory
                {namespace}. Did you mean one of these target names?\n
                """
                + bullet_list(f":{name}" for name in known_names)
            )
        )


@dataclass(frozen=True)
class MaybeAddress:
    """A target address, or an error if it could not be created.

    Use `Get(MaybeAddress, AddressInput)`, rather than the fallible variant
    `Get(Address, AddressInput)`.

    Note that this does not validate the address's target actually exists. It only validates that
    the address is well-formed and that its spec_path exists.

    Reminder: you may need to catch errors when creating the input `AddressInput` if the address is
    not well-formed.
    """

    val: Address | ResolveError
