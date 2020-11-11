# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, Sequence

from pants.base.deprecated import warn_or_error
from pants.engine.engine_aware import EngineAwareParameter
from pants.util.dirutil import fast_relpath, longest_dir_prefix
from pants.util.strutil import strip_prefix

# Currently unused, but reserved for possible future needs.
BANNED_CHARS_IN_TARGET_NAME = frozenset(r"@!?/\:=")


class InvalidSpecPath(ValueError):
    """Indicate an invalid spec path for `Address`."""


class InvalidTargetName(ValueError):
    """Indicate an invalid target name for `Address`."""


@dataclass(frozen=True)
class AddressInput:
    """A string that has been parsed and normalized using the Address syntax.

    An AddressInput must be resolved into an Address using the engine (which involves inspecting
    disk to determine the types of its components).
    """

    path_component: str
    target_component: Optional[str] = None

    def __post_init__(self):
        if self.target_component is not None or self.path_component == "":
            if not self.target_component:
                raise InvalidTargetName(
                    f"Address spec {self.path_component}:{self.target_component} has no name part."
                )

        # A root is okay.
        if self.path_component == "":
            return
        components = self.path_component.split(os.sep)
        if any(component in (".", "..", "") for component in components):
            raise InvalidSpecPath(
                f"Address spec has un-normalized path part '{self.path_component}'"
            )
        if os.path.isabs(self.path_component):
            raise InvalidSpecPath(
                f"Address spec has absolute path {self.path_component}; expected a path relative "
                "to the build root."
            )

    @classmethod
    def parse(
        cls,
        spec: str,
        relative_to: Optional[str] = None,
        subproject_roots: Optional[Sequence[str]] = None,
    ) -> "AddressInput":
        """Parse a string into an AddressInput.

        :param spec: Target address spec.
        :param relative_to: path to use for sibling specs, ie: ':another_in_same_build_family',
          interprets the missing spec_path part as `relative_to`.
        :param subproject_roots: Paths that correspond with embedded build roots under
          the current build root.

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

        spec_parts = spec.rsplit(":", 1)
        path_component = spec_parts[0]
        target_component = None if len(spec_parts) == 1 else spec_parts[1]

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

        return cls(path_component, target_component)

    def file_to_address(self) -> "Address":
        """Converts to an Address by assuming that the path_component is a file on disk."""
        if self.target_component is None:
            # Use the default target in the same directory as the file.
            spec_path, relative_file_path = os.path.split(self.path_component)
            # We validate that this is not a top-level file. We couldn't do this earlier in the
            # AddressSpec constructor because we weren't sure if the path_spec referred to a file
            # vs. a directory.
            if not spec_path:
                raise InvalidTargetName(
                    "Top-level file specs must include which target they come from, such as "
                    f"`{self.path_component}:original_target`, but {self.path_component} did not "
                    f"have an address."
                )
            return Address(spec_path=spec_path, relative_file_path=relative_file_path)

        # The target component may be "above" (but not below) the file in the filesystem.
        # Determine how many levels above the file it is, and validate that the path is relative.
        parent_count = self.target_component.count(os.path.sep)
        if parent_count == 0:
            spec_path, relative_file_path = os.path.split(self.path_component)
            return Address(
                spec_path=spec_path,
                relative_file_path=relative_file_path,
                target_name=self.target_component,
            )

        expected_prefix = f"..{os.path.sep}" * parent_count
        if self.target_component[: self.target_component.rfind(os.path.sep) + 1] != expected_prefix:
            raise InvalidTargetName(
                "A target may only be defined in a directory containing a file that it owns in "
                f"the filesystem: `{self.target_component}` is not at-or-above the file "
                f"`{self.path_component}`."
            )

        # Split the path_component into a spec_path and relative_file_path at the appropriate
        # position.
        path_components = self.path_component.split(os.path.sep)
        if len(path_components) <= parent_count:
            raise InvalidTargetName(
                "Targets are addressed relative to the files that they own: "
                f"`{self.target_component}` is too far above the file `{self.path_component}` to "
                "be valid."
            )
        offset = -1 * (parent_count + 1)
        spec_path = os.path.join(*path_components[:offset]) if path_components[:offset] else ""
        relative_file_path = os.path.join(*path_components[offset:])
        target_name = os.path.basename(self.target_component)
        return Address(spec_path, relative_file_path=relative_file_path, target_name=target_name)

    def dir_to_address(self) -> "Address":
        """Converts to an Address by assuming that the path_component is a directory on disk."""
        return Address(spec_path=self.path_component, target_name=self.target_component)


class Address(EngineAwareParameter):
    """A target address.

    An address is a unique name for a `pants.engine.target.Target`, and optionally a particular file
    that it owns.

    While not their only use, a noteworthy use of addresses is specifying
    target dependencies. For example:

        some_target(
            name='mytarget',
            dependencies=['path/to/buildfile:targetname'],
        )

    Where `path/to/buildfile:targetname` is the dependent target address.
    """

    def __init__(
        self,
        spec_path: str,
        *,
        relative_file_path: Optional[str] = None,
        target_name: Optional[str] = None,
    ) -> None:
        """
        :param spec_path: The path from the build root to the directory containing the BUILD file
          for the target.
        :param relative_file_path: The relative path from the spec_path to an addressed file,
          if any. Because files must always be located below targets that apply metadata to
          them, this will always be relative.
        :param target_name: The name of the target applying metadata to the file, defined in a
          BUILD file in the spec_path directory, or None if this path refers to the default
          target in that directory.
        """
        self.spec_path = spec_path
        self._relative_file_path = relative_file_path

        # If the target_name is the same as the default name would be, we normalize to None.
        self._target_name: Optional[str]
        if target_name and target_name != os.path.basename(self.spec_path):
            banned_chars = BANNED_CHARS_IN_TARGET_NAME & set(target_name)
            deprecated_banned_chars = banned_chars & set(r"/\:")
            if deprecated_banned_chars:
                warn_or_error(
                    removal_version="2.2.0.dev1",
                    deprecated_entity_description=(
                        r"Using any of the `\`, `/`, or `:` characters in a target name."
                    ),
                    hint=(
                        f"The target name {target_name} (defined in directory {self.spec_path}) "
                        f"contains deprecated characters (`{deprecated_banned_chars}`), which will "
                        "cause some usecases to fail. Please replace these characters with another "
                        "separator character like `_` or `-`."
                    ),
                )
            elif banned_chars:
                raise InvalidTargetName(
                    f"The target name {target_name} (defined in directory {self.spec_path}) "
                    f"contains banned characters (`{banned_chars}`). Please replace these "
                    "characters with another separator character like `_` or `-`."
                )
            self._target_name = target_name
        else:
            self._target_name = None

        self._hash = hash((self.spec_path, self._relative_file_path, self._target_name))
        if PurePath(spec_path).name.startswith("BUILD"):
            raise InvalidSpecPath(
                f"The address {self.spec} has {PurePath(spec_path).name} as the last part of its "
                f"path, but BUILD is a reserved name. Please make sure that you did not name any "
                f"directories BUILD."
            )

    @property
    def is_base_target(self) -> bool:
        return self._relative_file_path is None

    @property
    def is_default_target(self) -> bool:
        """True if this is address refers to the "default" target in the spec_path.

        The default target has a target name equal to the directory name.
        """
        return self._target_name is None

    @property
    def filename(self) -> str:
        if self._relative_file_path is None:
            raise ValueError("Only a file Address (`not self.is_base_target`) has a filename.")
        return os.path.join(self.spec_path, self._relative_file_path)

    @property
    def target_name(self) -> str:
        if self._target_name is None:
            return os.path.basename(self.spec_path)
        return self._target_name

    @property
    def spec(self) -> str:
        """The canonical string representation of the Address.

        Prepends '//' if the target is at the root, to disambiguate root-level targets
        from "relative" spec notation.

        :API: public
        """
        prefix = "//" if not self.spec_path else ""
        file_portion = f"{prefix}{self.spec_path}"
        if self._relative_file_path is not None:
            file_portion = os.path.join(file_portion, self._relative_file_path)

        # Relativize the target name to the dirname of the file.
        parent_prefix = (
            "../" * self._relative_file_path.count(os.path.sep) if self._relative_file_path else ""
        )
        if self._target_name is None and not parent_prefix:
            return file_portion
        target_name = self._target_name or os.path.basename(self.spec_path)
        return f"{file_portion}:{parent_prefix}{target_name}"

    @property
    def path_safe_spec(self) -> str:
        """
        :API: public
        """
        if self._relative_file_path:
            parent_count = self._relative_file_path.count(os.path.sep)
            parent_prefix = "@" * parent_count if parent_count else "."
            file_portion = f".{self._relative_file_path.replace(os.path.sep, '.')}"
        else:
            parent_prefix = "."
            file_portion = ""
        if parent_prefix == ".":
            target_portion = f"{parent_prefix}{self._target_name}" if self._target_name else ""
        else:
            target_name = self._target_name or os.path.basename(self.spec_path)
            target_portion = f"{parent_prefix}{target_name}"
        return f"{self.spec_path.replace(os.path.sep, '.')}{file_portion}{target_portion}"

    def maybe_convert_to_base_target(self) -> "Address":
        """If this address is a generated subtarget, convert it back into its original base target.

        Otherwise, return itself unmodified.

        TODO: This is not correct: we don't know the owning BUILD file of the base target without
        resolving. But it's possible that this method can be removed.
        """
        if self.is_base_target:
            return self
        return self.__class__(self.spec_path, relative_file_path=None, target_name=self.target_name)

    def __eq__(self, other):
        if not isinstance(other, Address):
            return False
        return (
            self.spec_path == other.spec_path
            and self._relative_file_path == other._relative_file_path
            and self._target_name == other._target_name
        )

    def __hash__(self):
        return self._hash

    def __repr__(self) -> str:
        return f"Address({self.spec})"

    def __str__(self) -> str:
        return self.spec

    def __lt__(self, other):
        return (self.spec_path, (self._relative_file_path or ""), (self._target_name or "")) < (
            other.spec_path,
            (other._relative_file_path or ""),
            (other._target_name or ""),
        )

    def debug_hint(self) -> str:
        return self.spec


@dataclass(frozen=True)
class BuildFileAddress:
    """Represents the address of a type materialized from a BUILD file.

    TODO: This type should likely be removed in favor of storing this information on Target.
    """

    address: Address
    # The relative path of the BUILD file this Address came from.
    rel_path: str
