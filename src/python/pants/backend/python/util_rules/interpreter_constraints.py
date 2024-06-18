# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from typing import Iterable, Iterator, Protocol, Sequence, Tuple, TypeVar

from packaging.requirements import InvalidRequirement
from pkg_resources import Requirement

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.target import Target
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap


# This protocol allows us to work with any arbitrary FieldSet. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class FieldSetWithInterpreterConstraints(Protocol):
    @property
    def address(self) -> Address: ...

    @property
    def interpreter_constraints(self) -> InterpreterConstraintsField: ...


_FS = TypeVar("_FS", bound=FieldSetWithInterpreterConstraints)


RawConstraints = Tuple[str, ...]


# The current maxes are 2.7.18 and 3.6.15.  We go much higher, for safety.
_PATCH_VERSION_UPPER_BOUND = 30


@memoized
def interpreter_constraints_contains(
    a: RawConstraints, b: RawConstraints, interpreter_universe: tuple[str, ...]
) -> bool:
    """A memoized version of `InterpreterConstraints.contains`.

    This is a function in order to keep the memoization cache on the module rather than on an
    instance. It can't go on `PythonSetup`, since that would cause a cycle with this module.
    """
    return InterpreterConstraints(a).contains(InterpreterConstraints(b), interpreter_universe)


@memoized
def parse_constraint(constraint: str) -> Requirement:
    """Parse an interpreter constraint, e.g., CPython>=2.7,<3.

    We allow shorthand such as `>=3.7`, which gets expanded to `CPython>=3.7`. See Pex's
    interpreter.py's `parse_requirement()`.
    """
    try:
        parsed_requirement = Requirement.parse(constraint)
    except ValueError as err:
        try:
            parsed_requirement = Requirement.parse(f"CPython{constraint}")
        except ValueError:
            raise InvalidRequirement(
                f"Failed to parse Python interpreter constraint `{constraint}`: {err.args[0]}"
            )

    return parsed_requirement


# Normally we would subclass `DeduplicatedCollection`, but we want a custom constructor.
class InterpreterConstraints(FrozenOrderedSet[Requirement], EngineAwareParameter):
    @classmethod
    def for_fixed_python_version(
        cls, python_version_str: str, interpreter_type: str = "CPython"
    ) -> InterpreterConstraints:
        return cls([f"{interpreter_type}=={python_version_str}"])

    def __init__(self, constraints: Iterable[str | Requirement] = ()) -> None:
        # #12578 `parse_constraint` will sort the requirement's component constraints into a stable form.
        # We need to sort the component constraints for each requirement _before_ sorting the entire list
        # for the ordering to be correct.
        parsed_constraints = (
            i if isinstance(i, Requirement) else parse_constraint(i) for i in constraints
        )
        super().__init__(sorted(parsed_constraints, key=lambda c: str(c)))

    def __str__(self) -> str:
        return " OR ".join(str(constraint) for constraint in self)

    def debug_hint(self) -> str:
        return str(self)

    @property
    def description(self) -> str:
        return str(sorted(str(c) for c in self))

    @classmethod
    def merge(cls, ics: Iterable[InterpreterConstraints]) -> InterpreterConstraints:
        return InterpreterConstraints(
            cls.merge_constraint_sets(tuple(str(requirement) for requirement in ic) for ic in ics)
        )

    @classmethod
    def merge_constraint_sets(
        cls, constraint_sets: Iterable[Iterable[str]]
    ) -> frozenset[Requirement]:
        """Given a collection of constraints sets, merge by ORing within each individual constraint
        set and ANDing across each distinct constraint set.

        For example, given `[["CPython>=2.7", "CPython<=3"], ["CPython==3.6.*"]]`, return
        `["CPython>=2.7,==3.6.*", "CPython<=3,==3.6.*"]`.
        """
        # A sentinel to indicate a requirement that is impossible to satisfy (i.e., one that
        # requires two different interpreter types).
        impossible = parse_constraint("IMPOSSIBLE")

        # Each element (a Set[ParsedConstraint]) will get ANDed. We use sets to deduplicate
        # identical top-level parsed constraint sets.

        # First filter out any empty constraint_sets, as those represent "no constraints", i.e.,
        # any interpreters are allowed, so omitting them has the logical effect of ANDing them with
        # the others, without having to deal with the vacuous case below.
        constraint_sets = [cs for cs in constraint_sets if cs]
        if not constraint_sets:
            return frozenset()

        parsed_constraint_sets: set[frozenset[Requirement]] = set()
        for constraint_set in constraint_sets:
            # Each element (a ParsedConstraint) will get ORed.
            parsed_constraint_set = frozenset(
                parse_constraint(constraint) for constraint in constraint_set
            )
            parsed_constraint_sets.add(parsed_constraint_set)

        if len(parsed_constraint_sets) == 1:
            return next(iter(parsed_constraint_sets))

        def and_constraints(parsed_constraints: Sequence[Requirement]) -> Requirement:
            merged_specs: set[tuple[str, str]] = set()
            expected_interpreter = parsed_constraints[0].project_name
            for parsed_constraint in parsed_constraints:
                if parsed_constraint.project_name != expected_interpreter:
                    return impossible
                merged_specs.update(parsed_constraint.specs)

            formatted_specs = ",".join(f"{op}{version}" for op, version in merged_specs)
            return parse_constraint(f"{expected_interpreter}{formatted_specs}")

        ored_constraints = (
            and_constraints(constraints_product)
            for constraints_product in itertools.product(*parsed_constraint_sets)
        )
        ret = frozenset(cs for cs in ored_constraints if cs != impossible)
        if not ret:
            # There are no possible combinations.
            attempted_str = " AND ".join(f"({' OR '.join(cs)})" for cs in constraint_sets)
            raise ValueError(
                softwrap(
                    f"""
                    These interpreter constraints cannot be merged, as they require
                    conflicting interpreter types: {attempted_str}
                    """
                )
            )
        return ret

    @classmethod
    def create_from_targets(
        cls, targets: Iterable[Target], python_setup: PythonSetup
    ) -> InterpreterConstraints | None:
        """Returns merged InterpreterConstraints for the given Targets.

        If none of the given Targets have InterpreterConstraintsField, returns None.

        NB: Because Python targets validate that they have ICs which are a subset of their
        dependencies, merging constraints like this is only necessary when you are _mixing_ code
        which might not have any interdependencies, such as when you're merging unrelated roots.
        """
        fields = [
            tgt[InterpreterConstraintsField]
            for tgt in targets
            if tgt.has_field(InterpreterConstraintsField)
        ]
        if not fields:
            return None
        return cls.create_from_compatibility_fields(fields, python_setup)

    @classmethod
    def create_from_compatibility_fields(
        cls, fields: Iterable[InterpreterConstraintsField], python_setup: PythonSetup
    ) -> InterpreterConstraints:
        """Returns merged InterpreterConstraints for the given `InterpreterConstraintsField`s.

        NB: Because Python targets validate that they have ICs which are a subset of their
        dependencies, merging constraints like this is only necessary when you are _mixing_ code
        which might not have any inter-dependencies, such as when you're merging un-related roots.
        """
        constraint_sets = {field.value_or_global_default(python_setup) for field in fields}
        # This will OR within each field and AND across fields.
        merged_constraints = cls.merge_constraint_sets(constraint_sets)
        return InterpreterConstraints(merged_constraints)

    @classmethod
    def group_field_sets_by_constraints(
        cls, field_sets: Iterable[_FS], python_setup: PythonSetup
    ) -> FrozenDict[InterpreterConstraints, tuple[_FS, ...]]:
        results = defaultdict(set)
        for fs in field_sets:
            constraints = cls.create_from_compatibility_fields(
                [fs.interpreter_constraints], python_setup
            )
            results[constraints].add(fs)
        return FrozenDict(
            {
                constraints: tuple(sorted(field_sets, key=lambda fs: fs.address))
                for constraints, field_sets in sorted(results.items())
            }
        )

    def generate_pex_arg_list(self) -> list[str]:
        args = []
        for constraint in self:
            args.extend(["--interpreter-constraint", str(constraint)])
        return args

    def _valid_patch_versions(self, major: int, minor: int) -> Iterator[int]:
        for p in range(0, _PATCH_VERSION_UPPER_BOUND + 1):
            for req in self:
                if req.specifier.contains(f"{major}.{minor}.{p}"):  # type: ignore[attr-defined]
                    yield p

    def _includes_version(self, major: int, minor: int) -> bool:
        return any(True for _ in self._valid_patch_versions(major, minor))

    def includes_python2(self) -> bool:
        """Checks if any of the constraints include Python 2.

        This will return True even if the code works with Python 3 too, so long as at least one of
        the constraints works with Python 2.
        """
        return self._includes_version(2, 7)

    def minimum_python_version(self, interpreter_universe: Iterable[str]) -> str | None:
        """Find the lowest major.minor Python version that will work with these constraints.

        The constraints may also be compatible with later versions; this is the lowest version that
        still works.
        """
        for major, minor in sorted(_major_minor_to_int(s) for s in interpreter_universe):
            if self._includes_version(major, minor):
                return f"{major}.{minor}"
        return None

    def snap_to_minimum(self, interpreter_universe: Iterable[str]) -> InterpreterConstraints | None:
        """Snap to the lowest Python major.minor version that works with these constraints.

        Will exclude patch versions that are expressly incompatible.
        """
        for major, minor in sorted(_major_minor_to_int(s) for s in interpreter_universe):
            for p in range(0, _PATCH_VERSION_UPPER_BOUND + 1):
                for req in self:
                    if req.specifier.contains(f"{major}.{minor}.{p}"):  # type: ignore[attr-defined]
                        # We've found the minimum major.minor that is compatible.
                        req_strs = [f"{req.project_name}=={major}.{minor}.*"]
                        # Now find any patches within that major.minor that we must exclude.
                        invalid_patches = sorted(
                            set(range(0, _PATCH_VERSION_UPPER_BOUND + 1))
                            - set(self._valid_patch_versions(major, minor))
                        )
                        req_strs.extend(f"!={major}.{minor}.{p}" for p in invalid_patches)
                        req_str = ",".join(req_strs)
                        snapped = parse_constraint(req_str)
                        return InterpreterConstraints([snapped])
        return None

    def _requires_python3_version_or_newer(
        self, *, allowed_versions: Iterable[str], prior_version: str
    ) -> bool:
        if not self:
            return False
        patch_versions = list(reversed(range(0, _PATCH_VERSION_UPPER_BOUND)))
        # We only look at the prior Python release. For example, consider Python 3.8+
        # looking at 3.7. If using something like `>=3.5`, Py37 will be included.
        # `==3.6.*,!=3.7.*,==3.8.*` is unlikely, and even that will work correctly as
        # it's an invalid constraint so setuptools returns False always. `['==2.7.*', '==3.8.*']`
        # will fail because not every single constraint is exclusively 3.8.
        prior_versions = [f"{prior_version}.{p}" for p in patch_versions]
        allowed_versions = [
            f"{major_minor}.{p}" for major_minor in allowed_versions for p in patch_versions
        ]

        def valid_constraint(constraint: Requirement) -> bool:
            if any(
                constraint.specifier.contains(prior) for prior in prior_versions  # type: ignore[attr-defined]
            ):
                return False
            if not any(
                constraint.specifier.contains(allowed) for allowed in allowed_versions  # type: ignore[attr-defined]
            ):
                return False
            return True

        return all(valid_constraint(c) for c in self)

    def requires_python38_or_newer(self, interpreter_universe: Iterable[str]) -> bool:
        """Checks if the constraints are all for Python 3.8+.

        This will return False if Python 3.8 is allowed, but prior versions like 3.7 are also
        allowed.
        """
        py38_and_later = [
            interp for interp in interpreter_universe if _major_minor_to_int(interp) >= (3, 8)
        ]
        return self._requires_python3_version_or_newer(
            allowed_versions=py38_and_later, prior_version="3.7"
        )

    def to_poetry_constraint(self) -> str:
        specifiers = []
        wildcard_encountered = False
        for constraint in self:
            specifier = str(constraint.specifier)  # type: ignore[attr-defined]
            if specifier:
                specifiers.append(specifier)
            else:
                wildcard_encountered = True
        if not specifiers or wildcard_encountered:
            return "*"
        return " || ".join(specifiers)

    def enumerate_python_versions(
        self, interpreter_universe: Iterable[str]
    ) -> FrozenOrderedSet[tuple[int, int, int]]:
        """Return a set of all plausible (major, minor, patch) tuples for all Python 2.7/3.x in the
        specified interpreter universe that matches this set of interpreter constraints.

        This also validates our assumptions around the `interpreter_universe`:

        - Python 2.7 is the only Python 2 version in the universe, if at all.
        - Python 3 is the last major release of Python, which the core devs have committed to in
          public several times.
        """
        if not self:
            return FrozenOrderedSet()

        minors = []
        for major_minor in interpreter_universe:
            major, minor = _major_minor_to_int(major_minor)
            if major == 2:
                if minor != 7:
                    raise AssertionError(
                        softwrap(
                            f"""
                            Unexpected value in `[python].interpreter_versions_universe`:
                            {major_minor}. Expected the only Python 2 value to be '2.7', given that
                            all other versions are unmaintained or do not exist.
                            """
                        )
                    )
                minors.append((2, minor))
            elif major == 3:
                minors.append((3, minor))
            else:
                raise AssertionError(
                    softwrap(
                        f"""
                        Unexpected value in `[python].interpreter_versions_universe`:
                        {major_minor}. Expected to only include '2.7' and/or Python 3 versions,
                        given that Python 3 will be the last major Python version. Please open an
                        issue at https://github.com/pantsbuild/pants/issues/new if this is no longer
                        true.
                        """
                    )
                )

        valid_patches = FrozenOrderedSet(
            (major, minor, patch)
            for (major, minor) in sorted(minors)
            for patch in self._valid_patch_versions(major, minor)
        )

        if not valid_patches:
            raise ValueError(
                softwrap(
                    f"""
                    The interpreter constraints `{self}` are not compatible with any of the
                    interpreter versions from `[python].interpreter_versions_universe`.

                    Please either change these interpreter constraints or update the
                    `interpreter_versions_universe` to include the interpreters set in these
                    constraints. Run `{bin_name()} help-advanced python` for more information on the
                    `interpreter_versions_universe` option.
                    """
                )
            )

        return valid_patches

    def contains(self, other: InterpreterConstraints, interpreter_universe: Iterable[str]) -> bool:
        """Returns True if the `InterpreterConstraints` specified in `other` is a subset of these
        `InterpreterConstraints`.

        This is restricted to the set of minor Python versions specified in `universe`.
        """
        if self == other:
            return True
        this = self.enumerate_python_versions(interpreter_universe)
        that = other.enumerate_python_versions(interpreter_universe)
        return this.issuperset(that)

    def partition_into_major_minor_versions(
        self, interpreter_universe: Iterable[str]
    ) -> tuple[str, ...]:
        """Return all the valid major.minor versions, e.g. `('2.7', '3.6')`."""
        result: OrderedSet[str] = OrderedSet()
        for major, minor, _ in self.enumerate_python_versions(interpreter_universe):
            result.add(f"{major}.{minor}")
        return tuple(result)

    def major_minor_version_when_single_and_entire(self) -> None | tuple[int, int]:
        """Returns the (major, minor) version that these constraints cover, if they cover all of
        exactly one major minor version, without rules about patch versions.

        This is a best effort function, e.g. for using during inference that can be overridden.

        Examples:

        All of these return (3, 9): `==3.9.*`, `CPython==3.9.*`, `>=3.9,<3.10`, `<3.10,>=3.9`

        All of these return None:

        - `==3.9.10`: restricted to a single patch version
        - `==3.9`: restricted to a single patch version (0, implicitly)
        - `==3.9.*,!=3.9.2`: excludes a patch
        - `>=3.9,<3.11`: more than one major version
        - `>=3.9,<3.11,!=3.10`: too complicated to understand it only includes 3.9
        - more than one requirement in the list: too complicated
        """

        try:
            return _major_minor_version_when_single_and_entire(self)
        except _NonSimpleMajorMinor:
            return None


def _major_minor_to_int(major_minor: str) -> tuple[int, int]:
    return tuple(int(x) for x in major_minor.split(".", maxsplit=1))  # type: ignore[return-value]


class _NonSimpleMajorMinor(Exception):
    pass


_ANY_PATCH_VERSION = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?P<any_patch>\.\*)?$")


def _parse_simple_version(version: str, require_any_patch: bool) -> tuple[int, int]:
    match = _ANY_PATCH_VERSION.fullmatch(version)
    if match is None or (require_any_patch and match.group("any_patch") is None):
        raise _NonSimpleMajorMinor()

    return int(match.group("major")), int(match.group("minor"))


def _major_minor_version_when_single_and_entire(ics: InterpreterConstraints) -> tuple[int, int]:
    if len(ics) != 1:
        raise _NonSimpleMajorMinor()

    req = next(iter(ics))

    just_cpython = req.project_name == "CPython" and not req.extras and not req.marker
    if not just_cpython:
        raise _NonSimpleMajorMinor()

    # ==major.minor or ==major.minor.*
    if len(req.specs) == 1:
        operator, version = next(iter(req.specs))
        if operator != "==":
            raise _NonSimpleMajorMinor()

        return _parse_simple_version(version, require_any_patch=True)

    # >=major.minor,<major.(minor+1)
    if len(req.specs) == 2:
        (operator_lo, version_lo), (operator_hi, version_hi) = iter(req.specs)

        if operator_lo != ">=":
            # if the lo operator isn't >=, they might be in the wrong order (or, if not, the check
            # below will catch them)
            operator_lo, operator_hi = operator_hi, operator_lo
            version_lo, version_hi = version_hi, version_lo

        if operator_lo != ">=" and operator_hi != "<":
            raise _NonSimpleMajorMinor()

        major_lo, minor_lo = _parse_simple_version(version_lo, require_any_patch=False)
        major_hi, minor_hi = _parse_simple_version(version_hi, require_any_patch=False)

        if major_lo == major_hi and minor_lo + 1 == minor_hi:
            return major_lo, minor_lo

        raise _NonSimpleMajorMinor()

    # anything else we don't understand
    raise _NonSimpleMajorMinor()
