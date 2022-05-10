# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference.rules import (
    InferConftestDependencies,
    InferInitDependencies,
    InferPythonImportDependencies,
    PythonInferSubsystem,
    UnownedDependencyError,
    UnownedDependencyUsage,
    import_rules,
    infer_python_conftest_dependencies,
    infer_python_init_dependencies,
)
from pants.backend.python.macros import python_requirements
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourceField,
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
from pants.engine.rules import SubsystemRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, engine_error
from pants.util.strutil import softwrap


def test_infer_python_imports(caplog) -> None:
    rule_runner = RuleRunner(
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
        args = ["--source-root-patterns=src/python"]
        if enable_string_imports:
            args.append("--python-infer-string-imports")
        rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies, [InferPythonImportDependencies(target[PythonSourceField])]
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
    rule_runner = RuleRunner(
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
            InferredDependencies, [InferPythonImportDependencies(target[PythonSourceField])]
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


def test_infer_python_inits() -> None:
    rule_runner = RuleRunner(
        rules=[
            *ancestor_files.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            infer_python_init_dependencies,
            SubsystemRule(PythonInferSubsystem),
            QueryRule(InferredDependencies, (InferInitDependencies,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )
    rule_runner.set_options(
        ["--python-infer-inits", "--source-root-patterns=src/python"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    rule_runner.write_files(
        {
            "src/python/root/__init__.py": "",
            "src/python/root/BUILD": "python_sources()",
            "src/python/root/mid/__init__.py": "",
            "src/python/root/mid/BUILD": "python_sources()",
            "src/python/root/mid/leaf/__init__.py": "",
            "src/python/root/mid/leaf/f.py": "",
            "src/python/root/mid/leaf/BUILD": "python_sources()",
            "src/python/type_stub/__init__.pyi": "",
            "src/python/type_stub/foo.pyi": "",
            "src/python/type_stub/BUILD": "python_sources()",
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [InferInitDependencies(target[PythonSourceField])],
        )

    assert run_dep_inference(
        Address("src/python/root/mid/leaf", relative_file_path="f.py")
    ) == InferredDependencies(
        [
            Address("src/python/root", relative_file_path="__init__.py"),
            Address("src/python/root/mid", relative_file_path="__init__.py"),
            Address("src/python/root/mid/leaf", relative_file_path="__init__.py"),
        ],
    )
    assert run_dep_inference(
        Address("src/python/type_stub", relative_file_path="foo.pyi")
    ) == InferredDependencies([Address("src/python/type_stub", relative_file_path="__init__.pyi")])


def test_infer_python_conftests() -> None:
    rule_runner = RuleRunner(
        rules=[
            *ancestor_files.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            infer_python_conftest_dependencies,
            SubsystemRule(PythonInferSubsystem),
            QueryRule(InferredDependencies, (InferConftestDependencies,)),
        ],
        target_types=[PythonTestsGeneratorTarget, PythonTestUtilsGeneratorTarget],
    )
    rule_runner.set_options(
        ["--source-root-patterns=src/python"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    rule_runner.write_files(
        {
            "src/python/root/conftest.py": "",
            "src/python/root/BUILD": "python_test_utils()",
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
            [InferConftestDependencies(target[PythonSourceField])],
        )

    assert run_dep_inference(
        Address(
            "src/python/root/mid/leaf", target_name="tests", relative_file_path="this_is_a_test.py"
        )
    ) == InferredDependencies(
        [
            Address("src/python/root", relative_file_path="conftest.py"),
            Address("src/python/root/mid", relative_file_path="conftest.py"),
            Address("src/python/root/mid/leaf", relative_file_path="conftest.py"),
        ],
    )


@pytest.fixture
def imports_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
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


def test_infer_python_strict(imports_rule_runner: RuleRunner, caplog) -> None:
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
            [InferPythonImportDependencies(target[PythonSourceField])],
        )

    run_dep_inference("warning")
    assert len(caplog.records) == 1
    assert (
        "cannot infer owners for the following imports in the target src/python/cheesey.py:"
        in caplog.text
    )
    assert "  * venezuelan_beaver_cheese (line: 1)" in caplog.text
    assert "japanese.sage.derby" not in caplog.text

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

    # All modes should be fine if the module is implictly found via requirements.txt
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


def test_infer_python_strict_multiple_resolves(imports_rule_runner: RuleRunner) -> None:
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
            InferredDependencies, [InferPythonImportDependencies(tgt[PythonSourceField])]
        )
