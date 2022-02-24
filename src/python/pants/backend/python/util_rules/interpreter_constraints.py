# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import itertools
from collections import defaultdict
from typing import Iterable, Iterator, Sequence, TypeVar

from pkg_resources import Requirement
from typing_extensions import Protocol

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.target import Target
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


# This protocol allows us to work with any arbitrary FieldSet. See
# https://mypy.readthedocs.io/en/stable/protocols.html.
class FieldSetWithInterpreterConstraints(Protocol):
    @property
    def address(self) -> Address:
        ...

    @property
    def interpreter_constraints(self) -> InterpreterConstraintsField:
        ...


_FS = TypeVar("_FS", bound=FieldSetWithInterpreterConstraints)


# The current maxes are 2.7.18 and 3.6.15.  We go much higher, for safety.
_PATCH_VERSION_UPPER_BOUND = 30


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
            i if isinstance(i, Requirement) else self.parse_constraint(i) for i in constraints
        )
        super().__init__(sorted(parsed_constraints, key=lambda c: str(c)))

    def __str__(self) -> str:
        return " OR ".join(str(constraint) for constraint in self)

    def debug_hint(self) -> str:
        return str(self)

    @staticmethod
    def parse_constraint(constraint: str) -> Requirement:
        """Parse an interpreter constraint, e.g., CPython>=2.7,<3.

        We allow shorthand such as `>=3.7`, which gets expanded to `CPython>=3.7`. See Pex's
        interpreter.py's `parse_requirement()`.
        """
        try:
            parsed_requirement = Requirement.parse(constraint)
        except ValueError:
            parsed_requirement = Requirement.parse(f"CPython{constraint}")
        return parsed_requirement

    @classmethod
    def merge_constraint_sets(cls, constraint_sets: Iterable[Iterable[str]]) -> list[Requirement]:
        """Given a collection of constraints sets, merge by ORing within each individual constraint
        set and ANDing across each distinct constraint set.

        For example, given `[["CPython>=2.7", "CPython<=3"], ["CPython==3.6.*"]]`, return
        `["CPython>=2.7,==3.6.*", "CPython<=3,==3.6.*"]`.
        """
        # Each element (a Set[ParsedConstraint]) will get ANDed. We use sets to deduplicate
        # identical top-level parsed constraint sets.
        if not constraint_sets:
            return []
        parsed_constraint_sets: set[frozenset[Requirement]] = set()
        for constraint_set in constraint_sets:
            # Each element (a ParsedConstraint) will get ORed.
            parsed_constraint_set = frozenset(
                cls.parse_constraint(constraint) for constraint in constraint_set
            )
            parsed_constraint_sets.add(parsed_constraint_set)

        def and_constraints(parsed_constraints: Sequence[Requirement]) -> Requirement:
            merged_specs: set[tuple[str, str]] = set()
            expected_interpreter = parsed_constraints[0].project_name
            for parsed_constraint in parsed_constraints:
                if parsed_constraint.project_name == expected_interpreter:
                    merged_specs.update(parsed_constraint.specs)
                    continue

                def key_fn(req: Requirement):
                    return req.project_name

                # NB: We must pre-sort the data for itertools.groupby() to work properly.
                sorted_constraints = sorted(parsed_constraints, key=key_fn)
                attempted_interpreters = {
                    interp: sorted(
                        str(parsed_constraint) for parsed_constraint in parsed_constraints
                    )
                    for interp, parsed_constraints in itertools.groupby(
                        sorted_constraints, key=key_fn
                    )
                }
                raise ValueError(
                    "Tried ANDing Python interpreter constraints with different interpreter "
                    "types. Please use only one interpreter type. Got "
                    f"{attempted_interpreters}."
                )

            formatted_specs = ",".join(f"{op}{version}" for op, version in merged_specs)
            return Requirement.parse(f"{expected_interpreter}{formatted_specs}")

        def cmp_constraints(req1: Requirement, req2: Requirement) -> int:
            if req1.project_name != req2.project_name:
                return -1 if req1.project_name < req2.project_name else 1
            if req1.specs == req2.specs:
                return 0
            return -1 if req1.specs < req2.specs else 1

        return sorted(
            {
                and_constraints(constraints_product)
                for constraints_product in itertools.product(*parsed_constraint_sets)
            },
            key=functools.cmp_to_key(cmp_constraints),
        )

    @classmethod
    def create_from_targets(
        cls, targets: Iterable[Target], python_setup: PythonSetup
    ) -> InterpreterConstraints:
        return cls.create_from_compatibility_fields(
            (
                tgt[InterpreterConstraintsField]
                for tgt in targets
                if tgt.has_field(InterpreterConstraintsField)
            ),
            python_setup,
        )

    @classmethod
    def create_from_compatibility_fields(
        cls, fields: Iterable[InterpreterConstraintsField], python_setup: PythonSetup
    ) -> InterpreterConstraints:
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
                        snapped = Requirement.parse(req_str)
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
                        "Unexpected value in `[python].interpreter_versions_universe`: "
                        f"{major_minor}. Expected the only Python 2 value to be '2.7', given that "
                        f"all other versions are unmaintained or do not exist."
                    )
                minors.append((2, minor))
            elif major == 3:
                minors.append((3, minor))
            else:
                raise AssertionError(
                    "Unexpected value in `[python].interpreter_versions_universe`: "
                    f"{major_minor}. Expected to only include '2.7' and/or Python 3 versions, "
                    "given that Python 3 will be the last major Python version. Please open an "
                    "issue at https://github.com/pantsbuild/pants/issues/new if this is no longer "
                    "true."
                )

        valid_patches = FrozenOrderedSet(
            (major, minor, patch)
            for (major, minor) in sorted(minors)
            for patch in self._valid_patch_versions(major, minor)
        )

        if not valid_patches:
            raise ValueError(
                f"The interpreter constraints `{self}` are not compatible with any of the "
                "interpreter versions from `[python].interpreter_versions_universe`.\n\n"
                "Please either change these interpreter constraints or update the "
                "`interpreter_versions_universe` to include the interpreters set in these "
                f"constraints. Run `{bin_name()} help-advanced python` for more information on the "
                "`interpreter_versions_universe` option."
            )

        return valid_patches

    def contains(self, other: InterpreterConstraints, interpreter_universe: Iterable[str]) -> bool:
        """Returns True if the `InterpreterConstraints` specified in `other` is a subset of these
        `InterpreterConstraints`.

        This is restricted to the set of minor Python versions specified in `universe`.
        """
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


def _major_minor_to_int(major_minor: str) -> tuple[int, int]:
    return tuple(int(x) for x in major_minor.split(".", maxsplit=1))  # type: ignore[return-value]
