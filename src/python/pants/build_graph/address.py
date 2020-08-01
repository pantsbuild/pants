# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Optional, Sequence

from pants.base.deprecated import deprecated
from pants.util.dirutil import fast_relpath, longest_dir_prefix
from pants.util.strutil import strip_prefix

# Currently unused, but reserved for possible future needs.
BANNED_CHARS_IN_TARGET_NAME = frozenset("@!?=")


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
    target_component: str

    def __post_init__(self):
        if not self.target_component:
            raise InvalidTargetName(
                f"Address spec {self.path_component}:{self.target_component} has no name part."
            )
        banned_chars = BANNED_CHARS_IN_TARGET_NAME & set(self.target_component)
        if banned_chars:
            raise InvalidTargetName(
                f"Banned chars found in target name. {banned_chars} not allowed in target "
                f"name: {self.target_component}"
            )

        # A root or relative spec is OK
        if self.path_component == "":
            return
        components = self.path_component.split(os.sep)
        if any(component in (".", "..", "") for component in components):
            raise InvalidSpecPath(
                f"Address spec has un-normalized path part '{self.path_component}'"
            )
        if components[-1].startswith("BUILD"):
            raise InvalidSpecPath(
                f"Address spec path {self.path_component} has {components[-1]} as the last path part and BUILD is "
                "a reserved file."
            )
        if os.path.isabs(self.path_component):
            raise InvalidSpecPath(
                f"Address spec has absolute path {self.path_component}; expected a path relative to the build "
                "root."
            )

    @classmethod
    def parse(
        cls,
        spec: str,
        relative_to: Optional[str] = None,
        subproject_roots: Optional[Sequence[str]] = None,
    ) -> "AddressInput":
        """
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

        In case the target name is empty, it returns the last component of the path as target name, ie:

            spec_path, target_name = _parse_spec('path/to/buildfile/foo')

        will return spec_path as 'path/to/buildfile/foo' and target_name as 'foo'.

        Optionally, specs can be prefixed with '//' to denote an absolute spec path.  This is normally
        not significant except when a spec referring to a root level target is needed from deeper in
        the tree. For example, in `path/to/buildfile/BUILD`:

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
        """
        subproject = (
            longest_dir_prefix(relative_to, subproject_roots)
            if relative_to and subproject_roots
            else None
        )

        def prefix_subproject(spec_path: str) -> str:
            if not subproject:
                return spec_path
            elif spec_path:
                return os.path.join(subproject, spec_path)
            else:
                return os.path.normpath(subproject)

        spec_parts = spec.rsplit(":", 1)
        if len(spec_parts) == 1:
            default_target_spec = spec_parts[0]
            path_component = prefix_subproject(strip_prefix(default_target_spec, "//"))
            target_component = os.path.basename(path_component)
        else:
            path_component, target_component = spec_parts
            if not path_component and relative_to:
                path_component = (
                    fast_relpath(relative_to, subproject) if subproject else relative_to
                )
            path_component = prefix_subproject(strip_prefix(path_component, "//"))

        return cls(path_component, target_component)

    def _unsafe_to_address(self) -> "Address":
        # NB: This will not remain correct: the only caller of this method is deprecated,
        # and AddressInputs should be converted to Addresses via the engine.
        return Address(self.path_component, self.target_component)


class Address:
    """A target address.

    An address is a unique name representing a
    `pants.engine.target.Target`. It's composed of the
    path from the root of the repo to the target plus the target name.

    While not their only use, a noteworthy use of addresses is specifying
    target dependencies. For example:

        some_target(
            name='mytarget',
            dependencies=['path/to/buildfile:targetname'],
        )

    Where `path/to/buildfile:targetname` is the dependent target address.
    """

    @classmethod
    @deprecated(
        "2.1.0.dev0",
        hint_message=(
            "An Address object should be resolved from an AddressInput using the engine. "
            "This does not work properly with generated subtargets."
        ),
    )
    def parse(cls, spec: str, relative_to: str = "", subproject_roots=None) -> "Address":
        """Parses an address from its serialized form.

        :param spec: An address in string form <path>:<name>.
        :param relative_to: For sibling specs, ie: ':another_in_same_build_family', interprets
                            the missing spec_path part as `relative_to`.
        :param list subproject_roots: Paths that correspond with embedded build roots
                                      under the current build root.
        """
        return AddressInput.parse(
            spec, relative_to=relative_to, subproject_roots=subproject_roots
        )._unsafe_to_address()

    def __init__(
        self, spec_path: str, target_name: str, *, generated_base_target_name: Optional[str] = None
    ) -> None:
        """
        :param spec_path: The path from the root of the repo to this target.
        :param target_name: The name of a target this Address refers to.
        :param generated_base_target_name: If this Address refers to a generated subtarget, this
                                           stores the target_name of the original base target.
        """
        self._spec_path = spec_path
        self._target_name = target_name
        self.generated_base_target_name = generated_base_target_name
        self._hash = hash((self._spec_path, self._target_name, self.generated_base_target_name))

    @property
    def spec_path(self) -> str:
        """The path from the build root to this target.

        :API: public
        """
        return self._spec_path

    @property
    def target_name(self) -> str:
        """
        :API: public
        """
        return self._target_name

    @property
    def spec(self) -> str:
        """The canonical string representation of the Address.

        Prepends '//' if the target is at the root, to disambiguate root-level targets
        from "relative" spec notation.

        :API: public
        """
        prefix = "//" if not self._spec_path else ""
        if self.generated_base_target_name:
            path = os.path.join(self._spec_path, self._target_name)
            return f"{prefix}{path}"
        return f"{prefix}{self._spec_path}:{self._target_name}"

    @property
    def path_safe_spec(self) -> str:
        """
        :API: public
        """
        return f"{self._spec_path.replace(os.sep, '.')}.{self._target_name.replace(os.sep, '.')}"

    @property
    def relative_spec(self) -> str:
        """
        :API: public
        """
        prefix = ":" if not self.generated_base_target_name else "./"
        return f"{prefix}{self._target_name}"

    def reference(self, referencing_path: Optional[str] = None) -> str:
        """How to reference this address in a BUILD file.

        :API: public
        """
        if referencing_path and self._spec_path == referencing_path:
            return self.relative_spec
        if os.path.basename(self._spec_path) != self._target_name:
            return self.spec
        return self._spec_path

    def maybe_convert_to_base_target(self) -> "Address":
        """If this address is a generated subtarget, convert it back into its original base target.

        Otherwise, return itself unmodified.
        """
        if not self.generated_base_target_name:
            return self
        return self.__class__(self._spec_path, target_name=self.generated_base_target_name)

    def __eq__(self, other):
        if not isinstance(other, Address):
            return False
        return (
            self._spec_path == other._spec_path
            and self._target_name == other._target_name
            and self.generated_base_target_name == other.generated_base_target_name
        )

    def __hash__(self):
        return self._hash

    def __repr__(self) -> str:
        prefix = f"Address({self.spec_path}, {self.target_name}"
        return (
            f"{prefix})"
            if not self.generated_base_target_name
            else f"{prefix}, generated_base_target_name={self.generated_base_target_name})"
        )

    def __str__(self) -> str:
        return self.spec

    def __lt__(self, other):
        return (self._spec_path, self._target_name, self.generated_base_target_name) < (
            other._spec_path,
            other._target_name,
            other.generated_base_target_name,
        )


@dataclass(frozen=True)
class BuildFileAddress:
    """Represents the address of a type materialized from a BUILD file.

    TODO: This type should likely be removed in favor of storing this information on Target.
    """

    address: Address
    # The relative path of the BUILD file this Address came from.
    rel_path: str
