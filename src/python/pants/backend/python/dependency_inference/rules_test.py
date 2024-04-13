# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference.module_mapper import PythonModuleOwners
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonImportInfo,
    ParsedPythonImports,
)
from pants.backend.python.dependency_inference.rules import (
    ConftestDependenciesInferenceFieldSet,
    ImportOwnerStatus,
    ImportResolveResult,
    InferConftestDependencies,
    InferInitDependencies,
    InferPythonImportDependencies,
    InitDependenciesInferenceFieldSet,
    PythonImportDependenciesInferenceFieldSet,
    UnownedDependencyError,
    UnownedImportsPossibleOwners,
    UnownedImportsPossibleOwnersRequest,
    _find_other_owners_for_unowned_imports,
    _get_imports_info,
    import_rules,
    infer_python_conftest_dependencies,
    infer_python_init_dependencies,
)
from pants.backend.python.dependency_inference.subsystem import (
    InitFilesInference,
    PythonInferSubsystem,
    UnownedDependencyUsage,
)
from pants.backend.python.macros import python_requirements
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.backend.python.util_rules import ancestor_files
from pants.core.target_types import FilesGeneratorTarget, ResourcesGeneratorTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Address
from pants.engine.internals.parametrize import Parametrize
from pants.engine.rules import rule
from pants.engine.target import ExplicitlyProvidedDependencies, InferredDependencies
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, engine_error
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


def assert_owners_not_found_error(
    target: str, error_message: str, not_found: Iterable[str] = (), found: Iterable[str] = ()
) -> None:
    """Assert that owners for certain imports were not found for a given target, and they are
    reported in the output error message."""
    assert f"cannot infer owners for the following imports in the target {target}:" in error_message
    for item in not_found:
        assert item in error_message

    for item in found:
        assert item not in error_message


def test_infer_python_imports(caplog) -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            *import_rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            QueryRule(InferredDependencies, [InferPythonImportDependencies]),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget],
    )
    rule_runner.write_files(
        {
            "3rdparty/python/BUILD": dedent(
                """\
                python_requirement(
                  name='Django',
                  requirements=['Django==1.21'],
                )
                """
            ),
            # If there's a `.py` and `.pyi` file for the same module, we should infer a dependency on both.
            "src/python/str_import/subdir/f.py": "",
            "src/python/str_import/subdir/f.pyi": "",
            "src/python/str_import/subdir/BUILD": "python_sources()",
            "src/python/util/dep.py": "",
            "src/python/util/BUILD": "python_sources()",
            "src/python/app.py": dedent(
                """\
                import django
                import unrecognized.module

                from util.dep import Demo
                from util import dep
                """
            ),
            "src/python/f2.py": dedent(
                """\
                import typing
                # Import from another file in the same target.
                from app import main

                # Dynamic string import.
                importlib.import_module('str_import.subdir.f')
                """
            ),
            "src/python/BUILD": "python_sources()",
        }
    )

    def run_dep_inference(
        address: Address, *, enable_string_imports: bool = False
    ) -> InferredDependencies:
        args = [
            "--source-root-patterns=src/python",
            "--python-infer-unowned-dependency-behavior=ignore",
        ]
        if enable_string_imports:
            args.append("--python-infer-string-imports")
        rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [
                InferPythonImportDependencies(
                    PythonImportDependenciesInferenceFieldSet.create(target)
                )
            ],
        )

    assert run_dep_inference(
        Address("src/python", relative_file_path="app.py")
    ) == InferredDependencies(
        [
            Address("3rdparty/python", target_name="Django"),
            Address("src/python/util", relative_file_path="dep.py"),
        ],
    )

    addr = Address("src/python", relative_file_path="f2.py")
    assert run_dep_inference(addr) == InferredDependencies(
        [Address("src/python", relative_file_path="app.py")]
    )
    assert run_dep_inference(addr, enable_string_imports=True) == InferredDependencies(
        [
            Address("src/python", relative_file_path="app.py"),
            Address("src/python/str_import/subdir", relative_file_path="f.py"),
            Address("src/python/str_import/subdir", relative_file_path="f.pyi"),
        ],
    )

    # Test handling of ambiguous imports. We should warn on the ambiguous dependency, but not warn
    # on the disambiguated one and should infer a dep.
    caplog.clear()
    rule_runner.write_files(
        {
            "src/python/ambiguous/dep.py": "",
            "src/python/ambiguous/disambiguated_via_ignores.py": "",
            "src/python/ambiguous/main.py": (
                "import ambiguous.dep\nimport ambiguous.disambiguated_via_ignores\n"
            ),
            "src/python/ambiguous/BUILD": dedent(
                """\
                python_sources(name='dep1', sources=['dep.py', 'disambiguated_via_ignores.py'])
                python_sources(name='dep2', sources=['dep.py', 'disambiguated_via_ignores.py'])
                python_sources(
                    name='main',
                    sources=['main.py'],
                    dependencies=['!./disambiguated_via_ignores.py:dep2'],
                )
                """
            ),
        }
    )
    assert run_dep_inference(
        Address("src/python/ambiguous", target_name="main", relative_file_path="main.py")
    ) == InferredDependencies(
        [
            Address(
                "src/python/ambiguous",
                target_name="dep1",
                relative_file_path="disambiguated_via_ignores.py",
            )
        ],
    )
    assert len(caplog.records) == 1
    assert "The target src/python/ambiguous/main.py:main imports `ambiguous.dep`" in caplog.text
    assert "['src/python/ambiguous/dep.py:dep1', 'src/python/ambiguous/dep.py:dep2']" in caplog.text
    assert "disambiguated_via_ignores.py" not in caplog.text


def test_infer_python_assets(caplog) -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            *import_rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            QueryRule(InferredDependencies, [InferPythonImportDependencies]),
        ],
        target_types=[
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            ResourcesGeneratorTarget,
            FilesGeneratorTarget,
        ],
    )
    rule_runner.write_files(
        {
            "src/python/data/BUILD": "resources(name='jsonfiles', sources=['*.json'])",
            "src/python/data/db.json": "",
            "src/python/data/db2.json": "",
            "src/python/data/flavors.txt": "",
            "configs/prod.txt": "",
            "src/python/app.py": dedent(
                """\
                pkgutil.get_data(__name__, "data/db.json")
                pkgutil.get_data(__name__, "data/db2.json")
                open("configs/prod.txt")
                """
            ),
            "src/python/f.py": dedent(
                """\
                idk_kinda_looks_resourcey = "data/db.json"
                CustomResourceType("data/flavors.txt")
                """
            ),
            "src/python/BUILD": dedent(
                """\
                python_sources()
                # Also test assets declared from parent dir
                resources(
                    name="txtfiles",
                    sources=["data/*.txt"],
                )
                """
            ),
            "configs/BUILD": dedent(
                """\
                files(
                    name="configs",
                    sources=["prod.txt"],
                )
                """
            ),
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        args = [
            "--source-root-patterns=src/python",
            "--python-infer-assets",
        ]
        rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [
                InferPythonImportDependencies(
                    PythonImportDependenciesInferenceFieldSet.create(target)
                )
            ],
        )

    assert run_dep_inference(
        Address("src/python", relative_file_path="app.py")
    ) == InferredDependencies(
        [
            Address("src/python/data", target_name="jsonfiles", relative_file_path="db.json"),
            Address("src/python/data", target_name="jsonfiles", relative_file_path="db2.json"),
            Address("configs", target_name="configs", relative_file_path="prod.txt"),
        ],
    )

    assert run_dep_inference(
        Address("src/python", relative_file_path="f.py")
    ) == InferredDependencies(
        [
            Address("src/python/data", target_name="jsonfiles", relative_file_path="db.json"),
            Address("src/python", target_name="txtfiles", relative_file_path="data/flavors.txt"),
        ],
    )

    # Test handling of ambiguous assets. We should warn on the ambiguous dependency, but not warn
    # on the disambiguated one and should infer a dep.
    caplog.clear()
    rule_runner.write_files(
        {
            "src/python/data/BUILD": dedent(
                """\
                    resources(name='jsonfiles', sources=['*.json'])
                    resources(name='also_jsonfiles', sources=['*.json'])
                    resources(name='txtfiles', sources=['*.txt'])
                """
            ),
            "src/python/data/ambiguous.json": "",
            "src/python/data/disambiguated_with_bang.json": "",
            "src/python/app.py": dedent(
                """\
                pkgutil.get_data(__name__, "data/ambiguous.json")
                pkgutil.get_data(__name__, "data/disambiguated_with_bang.json")
                """
            ),
            "src/python/BUILD": dedent(
                """\
                python_sources(
                    name="main",
                    dependencies=['!./data/disambiguated_with_bang.json:also_jsonfiles'],
                )
                """
            ),
            # Both a resource relative to the module and file with conspicuously similar paths
            "src/python/data/both_file_and_resource.txt": "",
            "data/both_file_and_resource.txt": "",
            "data/BUILD": "files(name='txtfiles', sources=['*.txt'])",
            "src/python/assets_bag.py": "ImAPathType('data/both_file_and_resource.txt')",
        }
    )
    assert run_dep_inference(
        Address("src/python", target_name="main", relative_file_path="app.py")
    ) == InferredDependencies(
        [
            Address(
                "src/python/data",
                target_name="jsonfiles",
                relative_file_path="disambiguated_with_bang.json",
            ),
        ],
    )
    assert len(caplog.records) == 1
    assert "The target src/python/app.py:main uses `data/ambiguous.json`" in caplog.text
    assert (
        "['src/python/data/ambiguous.json:also_jsonfiles', 'src/python/data/ambiguous.json:jsonfiles']"
        in caplog.text
    )
    assert "disambiguated_with_bang.py" not in caplog.text

    caplog.clear()
    assert run_dep_inference(
        Address("src/python", target_name="main", relative_file_path="assets_bag.py")
    ) == InferredDependencies([])
    assert len(caplog.records) == 1
    assert (
        "The target src/python/assets_bag.py:main uses `data/both_file_and_resource.txt`"
        in caplog.text
    )
    assert (
        "['data/both_file_and_resource.txt:txtfiles', 'src/python/data/both_file_and_resource.txt:txtfiles']"
        in caplog.text
    )


@pytest.mark.parametrize("behavior", InitFilesInference)
def test_infer_python_inits(behavior: InitFilesInference) -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            *ancestor_files.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            infer_python_init_dependencies,
            *PythonInferSubsystem.rules(),
            QueryRule(InferredDependencies, (InferInitDependencies,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
        objects={"parametrize": Parametrize},
    )
    rule_runner.set_options(
        [
            f"--python-infer-init-files={behavior.value}",
            "--python-resolves={'a': '', 'b': ''}",
            "--python-default-resolve=a",
            "--python-enable-resolves",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.write_files(
        {
            "src/python/root/__init__.py": "content",
            "src/python/root/BUILD": "python_sources(resolve=parametrize('a', 'b'))",
            "src/python/root/mid/__init__.py": "",
            "src/python/root/mid/BUILD": "python_sources()",
            "src/python/root/mid/leaf/__init__.py": "content",
            "src/python/root/mid/leaf/f.py": "",
            "src/python/root/mid/leaf/BUILD": "python_sources()",
            "src/python/type_stub/__init__.pyi": "content",
            "src/python/type_stub/foo.pyi": "",
            "src/python/type_stub/BUILD": "python_sources()",
        }
    )

    def check(address: Address, expected: list[Address]) -> None:
        target = rule_runner.get_target(address)
        result = rule_runner.request(
            InferredDependencies,
            [InferInitDependencies(InitDependenciesInferenceFieldSet.create(target))],
        )
        if behavior == InitFilesInference.never:
            expected = []

        assert result == InferredDependencies(expected)

    check(
        Address("src/python/root/mid/leaf", relative_file_path="f.py"),
        [
            Address(
                "src/python/root", relative_file_path="__init__.py", parameters={"resolve": "a"}
            ),
            *(
                []
                if behavior is InitFilesInference.content_only
                else [Address("src/python/root/mid", relative_file_path="__init__.py")]
            ),
            Address("src/python/root/mid/leaf", relative_file_path="__init__.py"),
        ],
    )
    check(
        Address("src/python/type_stub", relative_file_path="foo.pyi"),
        [Address("src/python/type_stub", relative_file_path="__init__.pyi")],
    )


def test_infer_python_conftests() -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            *ancestor_files.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            infer_python_conftest_dependencies,
            *PythonInferSubsystem.rules(),
            QueryRule(InferredDependencies, (InferConftestDependencies,)),
        ],
        target_types=[PythonTestsGeneratorTarget, PythonTestUtilsGeneratorTarget],
        objects={"parametrize": Parametrize},
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=src/python",
            "--python-resolves={'a': '', 'b': ''}",
            "--python-default-resolve=a",
            "--python-enable-resolves",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    rule_runner.write_files(
        {
            "src/python/root/conftest.py": "",
            "src/python/root/BUILD": "python_test_utils(resolve=parametrize('a', 'b'))",
            "src/python/root/mid/conftest.py": "",
            "src/python/root/mid/BUILD": "python_test_utils()",
            "src/python/root/mid/leaf/conftest.py": "",
            "src/python/root/mid/leaf/this_is_a_test.py": "",
            "src/python/root/mid/leaf/BUILD": "python_test_utils()\npython_tests(name='tests')",
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [InferConftestDependencies(ConftestDependenciesInferenceFieldSet.create(target))],
        )

    assert run_dep_inference(
        Address(
            "src/python/root/mid/leaf", target_name="tests", relative_file_path="this_is_a_test.py"
        )
    ) == InferredDependencies(
        [
            Address(
                "src/python/root", relative_file_path="conftest.py", parameters={"resolve": "a"}
            ),
            Address("src/python/root/mid", relative_file_path="conftest.py"),
            Address("src/python/root/mid/leaf", relative_file_path="conftest.py"),
        ],
    )


@pytest.fixture
def imports_rule_runner() -> PythonRuleRunner:
    return mk_imports_rule_runner([])


def mk_imports_rule_runner(more_rules: Iterable) -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *more_rules,
            *import_rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            *python_requirements.rules(),
            QueryRule(InferredDependencies, [InferPythonImportDependencies]),
        ],
        target_types=[
            PythonSourceTarget,
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            PythonRequirementsTargetGenerator,
        ],
        objects={"parametrize": Parametrize},
    )


def test_infer_python_ignore_unowned_imports(imports_rule_runner: PythonRuleRunner, caplog) -> None:
    """Test handling unowned imports that are set explicitly to be ignored."""
    imports_rule_runner.write_files(
        {
            "src/python/cheesey.py": dedent(
                """\
                    import unknown_python_requirement
                    import project.application.generated
                    import project.application.generated.loader
                    from project.application.generated import starter
                    import project.application.develop.client
                    import project.application.development
                """
            ),
            "src/python/BUILD": "python_sources()",
        }
    )

    def run_dep_inference(
        unowned_dependency_behavior: str, ignored_paths: tuple[str, ...] = tuple()
    ) -> InferredDependencies:
        imports_rule_runner.set_options(
            [
                f"--python-infer-unowned-dependency-behavior={unowned_dependency_behavior}",
                f"--python-infer-ignored-unowned-imports={str(list(ignored_paths))}",
            ],
            env_inherit=PYTHON_BOOTSTRAP_ENV,
        )
        target = imports_rule_runner.get_target(
            Address("src/python", relative_file_path="cheesey.py")
        )
        return imports_rule_runner.request(
            InferredDependencies,
            [
                InferPythonImportDependencies(
                    PythonImportDependenciesInferenceFieldSet.create(target)
                )
            ],
        )

    run_dep_inference("warning")
    assert len(caplog.records) == 1
    assert_owners_not_found_error(
        target="src/python/cheesey.py",
        not_found=[
            "unknown_python_requirement",
            "project.application.generated.starter",
            "project.application.generated.loader",
            "project.application.develop.client",
            "project.application.development",
        ],
        error_message=caplog.text,
    )

    # no error raised because unowned imports are explicitly ignored in the configuration
    run_dep_inference(
        "error",
        ignored_paths=(
            "unknown_python_requirement",
            "project.application.generated",
            "project.application.develop",
            "project.application.development",
        ),
    )

    # error raised because "project.application.development" is not ignored
    with engine_error(UnownedDependencyError, contains="src/python/cheesey.py"):
        run_dep_inference(
            "error",
            ignored_paths=(
                "unknown_python_requirement",
                "project.application.generated",
                "project.application.develop",
            ),
        )


def test_infer_python_strict(imports_rule_runner: PythonRuleRunner, caplog) -> None:
    imports_rule_runner.write_files(
        {
            "src/python/cheesey.py": dedent(
                """\
                    import venezuelan_beaver_cheese
                    "japanese.sage.derby"
                """
            ),
            "src/python/BUILD": "python_sources()",
        }
    )

    def run_dep_inference(unowned_dependency_behavior: str) -> InferredDependencies:
        imports_rule_runner.set_options(
            [
                f"--python-infer-unowned-dependency-behavior={unowned_dependency_behavior}",
                "--python-infer-string-imports",
            ],
            env_inherit=PYTHON_BOOTSTRAP_ENV,
        )
        target = imports_rule_runner.get_target(
            Address("src/python", relative_file_path="cheesey.py")
        )
        return imports_rule_runner.request(
            InferredDependencies,
            [
                InferPythonImportDependencies(
                    PythonImportDependenciesInferenceFieldSet.create(target)
                )
            ],
        )

    run_dep_inference("warning")
    assert len(caplog.records) == 1
    assert_owners_not_found_error(
        target="src/python/cheesey.py",
        not_found=[
            "  * venezuelan_beaver_cheese (line: 1)",
        ],
        found=[
            "japanese.sage.derby",
        ],
        error_message=caplog.text,
    )

    with engine_error(UnownedDependencyError, contains="src/python/cheesey.py"):
        run_dep_inference("error")

    caplog.clear()

    # All modes should be fine if the module is explicitly declared as a requirement
    imports_rule_runner.write_files(
        {
            "src/python/BUILD": dedent(
                """\
                    python_requirement(
                        name="venezuelan_beaver_cheese",
                        modules=["venezuelan_beaver_cheese"],
                        requirements=["venezuelan_beaver_cheese==1.0.0"],
                    )
                    python_sources(dependencies=[":venezuelan_beaver_cheese"])
                """
            ),
        }
    )
    for mode in UnownedDependencyUsage:
        run_dep_inference(mode.value)
        assert not caplog.records

    # All modes should be fine if the module is implicitly found via requirements.txt
    imports_rule_runner.write_files(
        {
            "src/python/requirements.txt": "venezuelan_beaver_cheese==1.0.0",
            "src/python/BUILD": dedent(
                """\
                    python_requirements(name='reqs')
                    python_sources()
                """
            ),
        }
    )
    for mode in UnownedDependencyUsage:
        run_dep_inference(mode.value)
        assert not caplog.records

    # All modes should be fine if the module is owned by a first party
    imports_rule_runner.write_files(
        {
            "src/python/venezuelan_beaver_cheese.py": "",
            "src/python/BUILD": "python_sources()",
        }
    )
    for mode in UnownedDependencyUsage:
        run_dep_inference(mode.value)
        assert not caplog.records


def test_infer_python_strict_multiple_resolves(imports_rule_runner: PythonRuleRunner) -> None:
    imports_rule_runner.write_files(
        {
            "project/base.py": "",
            "project/utils.py": "",
            "project/app.py": "import project.base\nimport project.utils",
            "project/BUILD": dedent(
                """\
                python_source(
                    name="base",
                    source="base.py",
                    resolve="a",
                )

                python_source(
                    name="utils",
                    source="utils.py",
                    resolve=parametrize("a", "b"),
                )

                python_source(
                    name="app",
                    source="app.py",
                    resolve="z",
                )
                """
            ),
        }
    )

    imports_rule_runner.set_options(
        [
            "--python-infer-unowned-dependency-behavior=error",
            "--python-enable-resolves",
            "--python-resolves={'a': '', 'b': '', 'z': ''}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    tgt = imports_rule_runner.get_target(Address("project", target_name="app"))
    expected_error = softwrap(
        """
        These imports are not in the resolve used by the target (`z`), but they were present in
        other resolves:

          * project.base: 'a' from project:base
          * project.utils: 'a' from project:utils@resolve=a, 'b' from project:utils@resolve=b
        """
    )
    with engine_error(UnownedDependencyError, contains=expected_error):
        imports_rule_runner.request(
            InferredDependencies,
            [InferPythonImportDependencies(PythonImportDependenciesInferenceFieldSet.create(tgt))],
        )


def test_infer_python_identical_files_with_relative_imports_should_be_treated_differently(
    imports_rule_runner: PythonRuleRunner,
) -> None:
    # dependency inference shouldn't cache _just_ based on file contents, because this can break
    # relative imports. When b reused a's results, b/__init__.py was incorrectly depending on
    # a/file.py (https://github.com/pantsbuild/pants/issues/19618).
    contents = "from . import file"
    imports_rule_runner.write_files(
        {
            "a/BUILD": "python_sources()",
            "a/__init__.py": contents,
            "a/file.py": "",
            "b/BUILD": "python_sources()",
            "b/__init__.py": contents,
            "b/file.py": "",
        }
    )

    def get_deps(directory: str) -> InferredDependencies:
        tgt = imports_rule_runner.get_target(
            Address(directory, target_name=directory, relative_file_path="__init__.py")
        )

        return imports_rule_runner.request(
            InferredDependencies,
            [InferPythonImportDependencies(PythonImportDependenciesInferenceFieldSet.create(tgt))],
        )

    # first, seed the cache with the deps for "a"
    assert get_deps("a") == InferredDependencies(
        [
            Address("a", target_name="a", relative_file_path="file.py"),
        ]
    )

    # then, run with "b", which _shouldn't_ reuse the cache from the previous run to give
    # "a/file.py:a" (as it did previously, see #19618), and should instead give "b/file.py:b"
    assert get_deps("b") == InferredDependencies(
        [
            Address("b", target_name="b", relative_file_path="file.py"),
        ]
    )


class TestCategoriseImportsInfo:
    address = Address("sample/path")
    import_cases = {
        "unambiguous": (
            ParsedPythonImportInfo(0, False),
            PythonModuleOwners((Address("unambiguous.py"),)),
        ),
        "unambiguous_with_pyi": (
            ParsedPythonImportInfo(0, False),
            PythonModuleOwners(
                (
                    Address("unambiguous_with_pyi.py"),
                    Address("unambiguous_with_pyi.pyi"),
                )
            ),
        ),
        "ambiguous_disambiguatable": (
            ParsedPythonImportInfo(0, False),
            PythonModuleOwners(
                tuple(),
                (
                    Address("ambiguous_disambiguatable", target_name="good"),
                    Address("ambiguous_disambiguatable", target_name="bad"),
                ),
            ),
        ),
        "ambiguous_terminal": (
            ParsedPythonImportInfo(0, False),
            PythonModuleOwners(
                tuple(),
                (
                    Address("ambiguous_disambiguatable", target_name="bad0"),
                    Address("ambiguous_disambiguatable", target_name="bad1"),
                ),
            ),
        ),
        "json": (
            ParsedPythonImportInfo(0, False),
            PythonModuleOwners(tuple()),
        ),  # unownable
        "os.path": (
            ParsedPythonImportInfo(0, False),
            PythonModuleOwners(tuple()),
        ),  # unownable, not root module
        "weak_owned": (
            ParsedPythonImportInfo(0, True),
            PythonModuleOwners((Address("weak_owned.py"),)),
        ),
        "weak_unowned": (
            ParsedPythonImportInfo(0, True),
            PythonModuleOwners(tuple()),
        ),
        "unowned": (
            ParsedPythonImportInfo(0, False),
            PythonModuleOwners(tuple()),
        ),
    }

    def filter_case(self, case_name: str, cases=None):
        cases = cases or self.import_cases
        return {case_name: cases[case_name]}

    def separate_owners_and_imports(
        self,
        imports_to_owners: dict[str, tuple[ParsedPythonImportInfo, PythonModuleOwners]],
    ) -> tuple[list[PythonModuleOwners], ParsedPythonImports]:
        owners_per_import = [x[1] for x in imports_to_owners.values()]
        parsed_imports = ParsedPythonImports({k: v[0] for k, v in imports_to_owners.items()})
        return owners_per_import, parsed_imports

    def do_test(self, case_name: str, expected_status: ImportOwnerStatus) -> ImportResolveResult:
        owners_per_import, parsed_imports = self.separate_owners_and_imports(
            self.filter_case(case_name)
        )
        resolve_result = _get_imports_info(
            self.address,
            owners_per_import,
            parsed_imports,
            ExplicitlyProvidedDependencies(
                self.address,
                FrozenOrderedSet(),
                FrozenOrderedSet((Address("ambiguous_disambiguatable", target_name="bad"),)),
            ),
        )

        assert len(resolve_result) == 1 and case_name in resolve_result
        resolved = resolve_result[case_name]
        assert resolved.status == expected_status
        return resolved

    def test_unambiguous_imports(self, imports_rule_runner: PythonRuleRunner) -> None:
        case_name = "unambiguous"
        resolved = self.do_test(case_name, ImportOwnerStatus.unambiguous)
        assert resolved.address == self.import_cases[case_name][1].unambiguous

    def test_unambiguous_with_pyi(self, imports_rule_runner: PythonRuleRunner) -> None:
        case_name = "unambiguous_with_pyi"
        resolved = self.do_test(case_name, ImportOwnerStatus.unambiguous)
        assert resolved.address == self.import_cases[case_name][1].unambiguous

    def test_unownable_root(self, imports_rule_runner: PythonRuleRunner) -> None:
        case_name = "json"
        self.do_test(case_name, ImportOwnerStatus.unownable)

    def test_unownable_nonroot(self, imports_rule_runner: PythonRuleRunner) -> None:
        case_name = "os.path"
        self.do_test(case_name, ImportOwnerStatus.unownable)

    def test_weak_owned(self, imports_rule_runner: PythonRuleRunner) -> None:
        case_name = "weak_owned"
        resolved = self.do_test(case_name, ImportOwnerStatus.unambiguous)
        assert resolved.address == self.import_cases[case_name][1].unambiguous

    def test_weak_unowned(self, imports_rule_runner: PythonRuleRunner) -> None:
        case_name = "weak_unowned"
        resolved = self.do_test(case_name, ImportOwnerStatus.weak_ignore)
        assert resolved.address == tuple()

    def test_unowned(self, imports_rule_runner: PythonRuleRunner) -> None:
        case_name = "unowned"
        resolved = self.do_test(case_name, ImportOwnerStatus.unowned)
        assert resolved.address == tuple()

    def test_ambiguous_disambiguatable(self):
        case_name = "ambiguous_disambiguatable"
        resolved = self.do_test(case_name, ImportOwnerStatus.disambiguated)
        assert resolved.address == (self.import_cases[case_name][1].ambiguous[0],)

    def test_ambiguous_not_disambiguatable(self):
        case_name = "ambiguous_terminal"
        resolved = self.do_test(case_name, ImportOwnerStatus.unowned)
        assert resolved.address == ()


class TestFindOtherOwners:
    missing_import_name = "missing"
    other_resolve = "other-resolve"
    other_other_resolve = "other-other-resolve"

    @staticmethod
    @rule
    async def run_rule(
        req: UnownedImportsPossibleOwnersRequest,
    ) -> UnownedImportsPossibleOwners:
        return await _find_other_owners_for_unowned_imports(req)

    @pytest.fixture
    def _imports_rule_runner(self):
        return mk_imports_rule_runner(
            [
                self.run_rule,
                QueryRule(UnownedImportsPossibleOwners, [UnownedImportsPossibleOwnersRequest]),
            ]
        )

    def do_test(self, imports_rule_runner: PythonRuleRunner):
        resolves = {"python-default": "", self.other_resolve: "", self.other_other_resolve: ""}
        imports_rule_runner.set_options(
            [
                "--python-enable-resolves",
                f"--python-resolves={resolves}",
            ]
        )

        imports_rule_runner.write_files(
            {
                "project/cheesey.py": dedent(
                    f"""\
                        import other.{self.missing_import_name}
                    """
                ),
                "project/BUILD": "python_sources()",
            }
        )

        return imports_rule_runner.request(
            UnownedImportsPossibleOwners,
            [
                UnownedImportsPossibleOwnersRequest(
                    frozenset((f"other.{self.missing_import_name}",)), "original_resolve"
                )
            ],
        )

    def test_no_other_owners_found(self, _imports_rule_runner):
        r = self.do_test(_imports_rule_runner)
        assert not r.value

    def test_other_owners_found_in_single_resolve(self, _imports_rule_runner: PythonRuleRunner):
        _imports_rule_runner.write_files(
            {
                "other/BUILD": dedent(
                    f"""\
                    python_source(
                        name="{self.missing_import_name}",
                        source="{self.missing_import_name}.py",
                        resolve="{self.other_resolve}",
                    )
                """
                ),
                f"other/{self.missing_import_name}.py": "",
            }
        )

        r = self.do_test(_imports_rule_runner)

        as_module = f"other.{self.missing_import_name}"
        assert as_module in r.value
        assert r.value[as_module] == [
            (
                Address("other", target_name=self.missing_import_name),
                self.other_resolve,
            )
        ]

    def test_other_owners_found_in_multiple_resolves(self, _imports_rule_runner: PythonRuleRunner):
        _imports_rule_runner.write_files(
            {
                "other/BUILD": dedent(
                    f"""\
                    python_source(
                        name="{self.missing_import_name}",
                        source="{self.missing_import_name}.py",
                        resolve=parametrize("{self.other_resolve}", "{self.other_other_resolve}"),
                    )
                """
                ),
                f"other/{self.missing_import_name}.py": "",
            }
        )

        r = self.do_test(_imports_rule_runner)

        as_module = f"other.{self.missing_import_name}"
        assert as_module in r.value
        assert r.value[as_module] == [
            (
                Address(
                    "other",
                    target_name=self.missing_import_name,
                    parameters={"resolve": resolve},
                ),
                resolve,
            )
            for resolve in (self.other_other_resolve, self.other_resolve)
        ]
