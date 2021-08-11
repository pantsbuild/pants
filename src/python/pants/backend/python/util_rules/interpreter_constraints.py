# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import itertools
from collections import defaultdict
from typing import FrozenSet, Iterable, Iterator, List, Sequence, Set, Tuple, TypeVar

from packaging.specifiers import SpecifierSet
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
    ) -> FrozenDict[InterpreterConstraints, Tuple[_FS, ...]]:
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
        for p in range(0, _EXPECTED_LAST_PATCH_VERSION + 1):
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

    def _requires_python3_version_or_newer(
        self, *, allowed_versions: Iterable[str], prior_version: str
    ) -> bool:
        if not self:
            return False
        patch_versions = list(reversed(range(0, _EXPECTED_LAST_PATCH_VERSION)))
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

    def flatten(self, interpreter_universe: Iterable[str]) -> SpecifierSet:
        """Flatten into a single specifier set.

        Each element in the original list gets ORed, which we must preserve. We do this by including
        the whole universe but excluding anything not in the original range.

        Note that this does not preserve the interpreter name, e.g. `PyPy` vs. `CPython`. This is
        to handle when users OR different interpreters, like CPython==3.7.* OR PyPY==3.7.*.
        """
        if not self:
            return SpecifierSet("")
        if len(self) == 1:
            return next(iter(self)).specifier  # type: ignore[attr-defined,no-any-return]

        # Strategy: find the upper and lower bounds, while also finding any versions to skip.
        # To make the result more readable, try to consolidate when possible, e.g. prefer
        # `!=3.2.*` over `!=3.2,0,!=3.2.1` and so on.
        valid_py27_patches, valid_py3_patches = self._determine_all_valid_py2_and_py3_patches(
            interpreter_universe
        )
        if not valid_py27_patches and not valid_py3_patches:
            return SpecifierSet("")

        lower_bound: str | None = None
        upper_bound: str | None = None
        skipped: list[str] = []

        def _combine_bounds_and_skipped_into_result() -> SpecifierSet:
            result = f"{lower_bound},{upper_bound}"
            if skipped:
                result += "," + ",".join(f"!={v}" for v in skipped)
            return Requirement.parse(  # type:ignore[no-any-return,attr-defined]
                f"doesnt-matter{result}"
            ).specifier

        if valid_py27_patches:
            lower_bound = _determine_lower_bound(2, 7, valid_py27_patches[0])
            skipped.extend(
                _determine_skipped(
                    2,
                    7,
                    valid_py27_patches,
                    major_minor_is_lower_bound=True,
                    major_minor_is_upper_bound=not valid_py3_patches,
                )
            )
            if not valid_py3_patches:
                upper_bound = _determine_upper_bound(2, 7, valid_py27_patches[-1])
                return _combine_bounds_and_skipped_into_result()

        assert valid_py3_patches
        all_valid_py3_versions = list(valid_py3_patches)
        first_py3_version = all_valid_py3_versions[0]
        last_py3_version = all_valid_py3_versions[-1]
        only_one_py3_version = first_py3_version == last_py3_version

        first_py3_version_patches = valid_py3_patches[first_py3_version]
        last_py3_version_patches = valid_py3_patches[last_py3_version]

        # Either skip all Py3 versions between 2.7 and the first Py3 version, or set that Py3
        # version as the lower bound if Py27 not in use.
        if valid_py27_patches:
            skipped.extend(f"3.{m}.*" for m in range(0, first_py3_version))
        else:
            assert lower_bound is None
            lower_bound = _determine_lower_bound(3, first_py3_version, first_py3_version_patches[0])
        assert lower_bound is not None

        # Skip all invalid patches in the first Py3 minor version.
        skipped.extend(
            _determine_skipped(
                3,
                first_py3_version,
                first_py3_version_patches,
                major_minor_is_lower_bound=not valid_py27_patches,
                major_minor_is_upper_bound=only_one_py3_version,
            )
        )

        # If there is only one Py3 version, set that as the upper bound and return.
        if only_one_py3_version:
            upper_bound = _determine_upper_bound(
                3, first_py3_version, first_py3_version_patches[-1]
            )
            return _combine_bounds_and_skipped_into_result()

        # Skip any Py3 versions between the lowest Py3 version and last Py3 version.
        # This `range()` will do nothing if there are no versions between.
        for py3_minor in range(first_py3_version + 1, last_py3_version):
            if py3_minor in valid_py3_patches:
                skipped.extend(
                    _determine_skipped(
                        3,
                        py3_minor,
                        valid_py3_patches[py3_minor],
                        major_minor_is_lower_bound=False,
                        major_minor_is_upper_bound=False,
                    )
                )
            else:
                skipped.append(f"3.{py3_minor}.*")

        # Finally, set the upper bound to the last Py3 version.
        upper_bound = _determine_upper_bound(3, last_py3_version, last_py3_version_patches[-1])
        skipped.extend(
            _determine_skipped(
                3,
                last_py3_version,
                last_py3_version_patches,
                major_minor_is_lower_bound=False,
                major_minor_is_upper_bound=True,
            )
        )

        return _combine_bounds_and_skipped_into_result()

    def _determine_all_valid_py2_and_py3_patches(
        self, interpreter_universe: Iterable[str]
    ) -> tuple[list[int], dict[int, list[int]]]:
        """Return a list of all valid Python 2.7 patches and a dictionary of all Python 3 minor
        versions to their valid patches, if any.

        This also validates our assumptions around the `interpreter_universe`:

        - Python 2.7 is the only Python 2 version in the universe, if at all.
        - Python 3 is the last major release of Python, which the core devs have committed to in
          public several times.
        """
        if not self:
            return ([], {})

        py2_minors = []
        py3_minors = []
        for major_minor in interpreter_universe:
            major, minor = _major_minor_to_int(major_minor)
            if major == 2:
                if minor != 7:
                    raise AssertionError(
                        "Unexpected value in `[python-setup].interpreter_versions_universe`: "
                        f"{major_minor}. Expected the only Python 2 value to be '2.7', given that "
                        f"all other versions are unmaintained or do not exist."
                    )
                py2_minors.append(minor)
            elif major == 3:
                py3_minors.append(minor)
            else:
                raise AssertionError(
                    "Unexpected value in `[python-setup].interpreter_versions_universe`: "
                    f"{major_minor}. Expected to only include '2.7' and/or Python 3 versions, "
                    "given that Python 3 will be the last major Python version. Please open an "
                    "issue at https://github.com/pantsbuild/pants/issues/new if this is no longer "
                    "true."
                )

        valid_py27_patches = list(self._valid_patch_versions(2, 7)) if py2_minors else []
        valid_py3_patches: dict[int, list[int]] = {}
        for minor in sorted(py3_minors):
            valid_patches = list(self._valid_patch_versions(3, minor))
            if valid_patches:
                valid_py3_patches[minor] = valid_patches

        if not valid_py27_patches and not valid_py3_patches:
            raise ValueError(
                f"The interpreter constraints `{self}` are not compatible with any of the "
                "interpreter versions from `[python-setup].interpreter_versions_universe`.\n\n"
                "Please either change these interpreter constraints or update the "
                "`interpreter_versions_universe` to include the interpreters set in these "
                "constraints. Run `./pants help-advanced python-setup` for more information on the "
                "`interpreter_versions_universe` option."
            )

        return valid_py27_patches, valid_py3_patches


def _major_minor_to_int(major_minor: str) -> tuple[int, int]:
    return tuple(int(x) for x in major_minor.split(".", maxsplit=1))  # type: ignore[return-value]


def _determine_lower_bound(major: int, minor: int, first_valid_patch: int) -> str:
    return (
        f">={major}.{minor}" if first_valid_patch == 0 else f">={major}.{minor}.{first_valid_patch}"
    )


def _determine_upper_bound(major: int, minor: int, last_valid_patch: int) -> str:
    return (
        f"<{major}.{minor + 1}"
        if last_valid_patch == _EXPECTED_LAST_PATCH_VERSION
        else f"<={major}.{minor}.{last_valid_patch}"
    )


def _determine_skipped(
    major: int,
    minor: int,
    valid_patches: list[int],
    *,
    major_minor_is_lower_bound: bool,
    major_minor_is_upper_bound: bool,
) -> list[str]:
    start = valid_patches[0] if major_minor_is_lower_bound else 0
    end = valid_patches[-1] if major_minor_is_upper_bound else _EXPECTED_LAST_PATCH_VERSION + 1
    expected = set(range(start, end))
    invalid_patches = expected - set(valid_patches)
    return [f"{major}.{minor}.{p}" for p in invalid_patches]
