# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import itertools
from collections import defaultdict
from typing import FrozenSet, Iterable, List, Sequence, Set, Tuple, TypeVar

from pkg_resources import Requirement
from typing_extensions import Protocol

from pants.backend.python.target_types import InterpreterConstraintsField
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.target import Target
from pants.python.python_setup import PythonSetup
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


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


# The current maxes are 2.7.18 and 3.6.13.
_EXPECTED_LAST_PATCH_VERSION = 18


# Normally we would subclass `DeduplicatedCollection`, but we want a custom constructor.
class InterpreterConstraints(FrozenOrderedSet[Requirement], EngineAwareParameter):
    def __init__(self, constraints: Iterable[str | Requirement] = ()) -> None:
        super().__init__(
            v if isinstance(v, Requirement) else self.parse_constraint(v)
            for v in sorted(constraints, key=lambda c: str(c))
        )

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
    def merge_constraint_sets(cls, constraint_sets: Iterable[Iterable[str]]) -> List[Requirement]:
        """Given a collection of constraints sets, merge by ORing within each individual constraint
        set and ANDing across each distinct constraint set.

        For example, given `[["CPython>=2.7", "CPython<=3"], ["CPython==3.6.*"]]`, return
        `["CPython>=2.7,==3.6.*", "CPython<=3,==3.6.*"]`.
        """
        # Each element (a Set[ParsedConstraint]) will get ANDed. We use sets to deduplicate
        # identical top-level parsed constraint sets.
        if not constraint_sets:
            return []
        parsed_constraint_sets: Set[FrozenSet[Requirement]] = set()
        for constraint_set in constraint_sets:
            # Each element (a ParsedConstraint) will get ORed.
            parsed_constraint_set = frozenset(
                cls.parse_constraint(constraint) for constraint in constraint_set
            )
            parsed_constraint_sets.add(parsed_constraint_set)

        def and_constraints(parsed_constraints: Sequence[Requirement]) -> Requirement:
            merged_specs: Set[Tuple[str, str]] = set()
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
    ) -> FrozenDict["InterpreterConstraints", Tuple[_FS, ...]]:
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

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for constraint in self:
            args.extend(["--interpreter-constraint", str(constraint)])
        return args

    def _includes_version(
        self, major_minor: str, last_patch: int = _EXPECTED_LAST_PATCH_VERSION
    ) -> bool:
        patch_versions = list(reversed(range(0, last_patch + 1)))
        for req in self:
            if any(
                req.specifier.contains(f"{major_minor}.{p}") for p in patch_versions  # type: ignore[attr-defined]
            ):
                return True
        return False

    def includes_python2(self) -> bool:
        """Checks if any of the constraints include Python 2.

        This will return True even if the code works with Python 3 too, so long as at least one of
        the constraints works with Python 2.
        """
        return self._includes_version("2.7")

    def minimum_python_version(self, interpreter_universe: Iterable[str]) -> str | None:
        """Find the lowest major.minor Python version that will work with these constraints.

        The constraints may also be compatible with later versions; this is the lowest version that
        still works.
        """
        for major_minor in sorted(interpreter_universe, key=_major_minor_to_int):
            if self._includes_version(major_minor):
                return major_minor
        return None

    def _requires_python3_version_or_newer(
        self, *, allowed_versions: Iterable[str], prior_version: str
    ) -> bool:
        patch_versions = list(reversed(range(0, _EXPECTED_LAST_PATCH_VERSION)))
        # We only need to look at the prior Python release. For example, consider Python 3.8+
        # looking at 3.7. If using something like `>=3.5`, Py37 will be included.
        # `==3.6.*,!=3.7.*,==3.8.*` is extremely unlikely, and even that will work correctly as
        # it's an invalid constraint so setuptools returns False always. `['==2.7.*', '==3.8.*']`
        # will fail because not every single constraint is exclusively 3.8.
        prior_versions = [f"{prior_version}.{p}" for p in patch_versions]
        allowed_versions = [
            f"{major_minor}.{p}" for major_minor in allowed_versions for p in patch_versions
        ]
        for req in self:
            if any(
                req.specifier.contains(prior) for prior in prior_versions  # type: ignore[attr-defined]
            ):
                return False
            if not any(
                req.specifier.contains(allowed) for allowed in allowed_versions  # type: ignore[attr-defined]
            ):
                return False
        return True

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

    def partition_by_major_minor_versions(
        self, interpreter_universe: Iterable[str]
    ) -> tuple[InterpreterConstraints, ...]:
        """Create a distinct InterpreterConstraints value for each CPython major-minor version that
        is compatible with the original constraints."""
        if any(req.project_name != "CPython" for req in self):
            raise AssertionError(
                "This function only works with CPython interpreter constraints for now."
            )

        def all_valid_patch_versions(major_minor: str) -> list[int]:
            return [
                p
                for p in range(0, _EXPECTED_LAST_PATCH_VERSION + 1)
                for req in self
                if req.specifier.contains(f"{major_minor}.{p}")  # type: ignore[attr-defined]
            ]

        result = []

        def maybe_add_version(major_minor: str) -> None:
            major, minor = _major_minor_to_int(major_minor)
            next_major_minor = f"{major}.{minor + 1}"

            valid_patch_versions = all_valid_patch_versions(major_minor)
            if not valid_patch_versions:
                return

            if len(valid_patch_versions) == 1:
                result.append(
                    InterpreterConstraints([f"=={major_minor}.{valid_patch_versions[0]}"])
                )
                return

            skipped_patch_versions = _not_in_contiguous_range(valid_patch_versions)
            first_patch_supported = valid_patch_versions[0] == 0
            last_patch_supported = valid_patch_versions[-1] == _EXPECTED_LAST_PATCH_VERSION
            if not skipped_patch_versions and first_patch_supported and last_patch_supported:
                constraint = f"=={major_minor}.*"
            else:
                min_constraint = (
                    f">={major_minor}"
                    if first_patch_supported
                    else f">={major_minor}.{valid_patch_versions[0]}"
                )
                max_constraint = (
                    f"<{next_major_minor}"
                    if last_patch_supported
                    else f"<={major_minor}.{valid_patch_versions[-1]}"
                )
                if skipped_patch_versions:
                    skipped_constraints = ",".join(
                        f"!={major_minor}.{p}" for p in skipped_patch_versions
                    )
                    constraint = f"{min_constraint},{max_constraint},{skipped_constraints}"
                else:
                    constraint = f"{min_constraint},{max_constraint}"

            result.append(InterpreterConstraints([constraint]))

        for major_minor in sorted(interpreter_universe, key=_major_minor_to_int):
            maybe_add_version(major_minor)
        return tuple(result)

    def __str__(self) -> str:
        return " OR ".join(str(constraint) for constraint in self)

    def debug_hint(self) -> str:
        return str(self)


def _major_minor_to_int(major_minor: str) -> tuple[int, int]:
    return tuple(int(x) for x in major_minor.split(".", maxsplit=1))  # type: ignore[return-value]


def _not_in_contiguous_range(nums: list[int]) -> list[int]:
    # Expects list to already be sorted and have 1+ elements.
    expected = {i for i in range(nums[0], nums[-1])}
    return sorted(expected - set(nums))
