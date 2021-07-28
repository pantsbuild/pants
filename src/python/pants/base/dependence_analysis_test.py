# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import cast

from pants.backend.python.target_types import PythonLibrary, PythonSources
from pants.base.dependence_analysis import (
    DependenceAnalysis,
    DependenceAnalysisRequest,
    DependenceAnalysisResult,
    run_dependence_analysis,
)
from pants.base.specs import Specs
from pants.base.specs_parser import SpecsParser
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import rule
from pants.engine.target import Sources, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


class FortranSources(Sources):
    expected_file_extensions = (".f90",)


class FortranTestsSources(FortranSources):
    default = ("*_test.f90", "test_*.f90")


class FortranLibrarySources(FortranSources):
    default = ("*.f90",) + tuple(f"!{pat}" for pat in FortranTestsSources.default)


class FortranLibrary(Target):
    alias = "fortran_library"
    core_fields = (FortranLibrarySources,)


def setup_dependence_analysis(da_name, da_source_field_types, rule_impl):
    class AnalysisRequest(DependenceAnalysisRequest):
        source_field_types = da_source_field_types

    AnalysisRequest.__name__ = f"{da_name}{AnalysisRequest.__name__}"

    class Subsystem(GoalSubsystem):
        name = da_name.lower()

    Subsystem.__name__ = f"{da_name}{Subsystem.__name__}"

    class Test(Goal):
        subsystem_cls = Subsystem

    Test.__name__ = f"{da_name}{Test.__name__}"

    @rule
    async def analysis_rule(
        request: AnalysisRequest,
    ) -> DependenceAnalysisResult:
        return cast(DependenceAnalysisResult, rule_impl(Test, request))

    analysis_rule.__name__ = f"{da_name}{analysis_rule.__name__}"
    return Test, analysis_rule, UnionRule(DependenceAnalysisRequest, AnalysisRequest)


(
    transform_py_goal,
    transform_py_code_analysis_rule,
    transform_py_union_rule,
) = setup_dependence_analysis(
    "TransformPy",
    (PythonSources,),
    lambda goal, request: DependenceAnalysisResult(
        goal=goal,
        accesses=request.targets,
        mutates=request.targets,
    ),
)


(
    validate_py_goal,
    validate_py_code_analysis_rule,
    validate_py_union_rule,
) = setup_dependence_analysis(
    "ValidatePy",
    (PythonSources,),
    lambda goal, request: DependenceAnalysisResult(
        goal=goal, accesses=request.targets, mutates=None
    ),
)


(
    transform_fortran_goal,
    transform_fortran_code_analysis_rule,
    transform_fortran_union_rule,
) = setup_dependence_analysis(
    "TransformFortran",
    (FortranSources,),
    lambda goal, request: DependenceAnalysisResult(
        goal=goal,
        accesses=request.targets,
        mutates=request.targets,
    ),
)


(
    validate_fortran_goal,
    validate_fortran_code_analysis_rule,
    validate_fortran_union_rule,
) = setup_dependence_analysis(
    "ValidateFortran",
    (FortranSources,),
    lambda goal, request: DependenceAnalysisResult(
        goal=goal, accesses=request.targets, mutates=None
    ),
)


def test_dependence_analysis():
    rule_runner = RuleRunner(
        rules=[
            run_dependence_analysis,
            transform_py_code_analysis_rule,
            transform_py_union_rule,
            validate_py_code_analysis_rule,
            validate_py_union_rule,
            transform_fortran_code_analysis_rule,
            transform_fortran_union_rule,
            validate_fortran_code_analysis_rule,
            validate_fortran_union_rule,
            QueryRule(DependenceAnalysis, [Specs]),
        ],
        target_types=[
            FortranLibrary,
            PythonLibrary,
        ],
    )

    rule_runner.write_files(
        {
            "src/py/demo/BUILD": dedent(
                """
                python_library()
                """
            ),
            "src/fortran/demo/BUILD": dedent(
                """
                fortran_library()
                """
            ),
        }
    )

    parser = SpecsParser("/")

    def assert_analysis(addresses, goals):
        result = rule_runner.request(DependenceAnalysis, [parser.parse_specs(addresses)])

        assert result.goal_dependence_order == FrozenOrderedSet(goals)

    assert_analysis(
        ["src/py/demo"],
        [
            transform_py_goal,
            validate_py_goal,
        ],
    )

    assert_analysis(
        ["src/fortran/demo"],
        [transform_fortran_goal, validate_fortran_goal],
    )

    assert_analysis(
        [
            "src/py/demo",
            "src/fortran/demo",
        ],
        [
            transform_py_goal,
            transform_fortran_goal,
            validate_py_goal,
            validate_fortran_goal,
        ],
    )
