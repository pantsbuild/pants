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
from pants.backend.python.macros.python_requirements_caof import PythonRequirementsCAOF
from pants.backend.python.target_types import (
    PythonRequirementsFile,
    PythonRequirementTarget,
    PythonSourceField,
    PythonSourcesGeneratorTarget,
    PythonTestsGeneratorTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.backend.python.util_rules import ancestor_files
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import SubsystemRule
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_infer_python_imports(caplog) -> None:
    rule_runner = RuleRunner(
        rules=[
            *import_rules(),
            *target_types_rules.rules(),
            QueryRule(InferredDependencies, [InferPythonImportDependencies]),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget],
    )
    rule_runner.add_to_build_file(
        "3rdparty/python",
        dedent(
            """\
            python_requirement(
              name='Django',
              requirements=['Django==1.21'],
            )
            """
        ),
    )

    # If there's a `.py` and `.pyi` file for the same module, we should infer a dependency on both.
    rule_runner.create_file("src/python/str_import/subdir/f.py")
    rule_runner.create_file("src/python/str_import/subdir/f.pyi")
    rule_runner.add_to_build_file("src/python/str_import/subdir", "python_sources()")

    rule_runner.create_file("src/python/util/dep.py")
    rule_runner.add_to_build_file("src/python/util", "python_sources()")

    rule_runner.create_file(
        "src/python/app.py",
        dedent(
            """\
            import django
            import unrecognized.module

            from util.dep import Demo
            from util import dep
            """
        ),
    )
    rule_runner.create_file(
        "src/python/f2.py",
        dedent(
            """\
            import typing
            # Import from another file in the same target.
            from app import main

            # Dynamic string import.
            importlib.import_module('str_import.subdir.f')
            """
        ),
    )
    rule_runner.add_to_build_file("src/python", "python_sources()")

    def run_dep_inference(
        address: Address, *, enable_string_imports: bool = False
    ) -> InferredDependencies:
        args = ["--backend-packages=pants.backend.python", "--source-root-patterns=src/python"]
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
    rule_runner.create_files("src/python/ambiguous", ["dep.py", "disambiguated_via_ignores.py"])
    rule_runner.create_file(
        "src/python/ambiguous/main.py",
        "import ambiguous.dep\nimport ambiguous.disambiguated_via_ignores\n",
    )
    rule_runner.add_to_build_file(
        "src/python/ambiguous",
        dedent(
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


def test_infer_python_inits() -> None:
    rule_runner = RuleRunner(
        rules=[
            *ancestor_files.rules(),
            *target_types_rules.rules(),
            infer_python_init_dependencies,
            SubsystemRule(PythonInferSubsystem),
            QueryRule(InferredDependencies, (InferInitDependencies,)),
        ],
        target_types=[PythonSourcesGeneratorTarget],
    )
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
            "--python-infer-inits",
            "--source-root-patterns=src/python",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    rule_runner.create_file("src/python/root/__init__.py")
    rule_runner.add_to_build_file("src/python/root", "python_sources()")

    rule_runner.create_file("src/python/root/mid/__init__.py")
    rule_runner.add_to_build_file("src/python/root/mid", "python_sources()")

    rule_runner.create_file("src/python/root/mid/leaf/__init__.py")
    rule_runner.create_file("src/python/root/mid/leaf/f.py")
    rule_runner.add_to_build_file("src/python/root/mid/leaf", "python_sources()")

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


def test_infer_python_conftests() -> None:
    rule_runner = RuleRunner(
        rules=[
            *ancestor_files.rules(),
            *target_types_rules.rules(),
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

    rule_runner.create_file("src/python/root/conftest.py")
    rule_runner.add_to_build_file("src/python/root", "python_test_utils()")

    rule_runner.create_file("src/python/root/mid/conftest.py")
    rule_runner.add_to_build_file("src/python/root/mid", "python_test_utils()")

    rule_runner.create_file("src/python/root/mid/leaf/conftest.py")
    rule_runner.create_file("src/python/root/mid/leaf/this_is_a_test.py")
    rule_runner.add_to_build_file(
        "src/python/root/mid/leaf", "python_test_utils()\npython_tests(name='tests')"
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


def test_infer_python_strict(caplog) -> None:
    rule_runner = RuleRunner(
        rules=[
            *import_rules(),
            *target_types_rules.rules(),
            QueryRule(InferredDependencies, [InferPythonImportDependencies]),
        ],
        target_types=[
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            PythonRequirementsFile,
        ],
        context_aware_object_factories={"python_requirements": PythonRequirementsCAOF},
    )

    rule_runner.create_file(
        "src/python/cheesey.py",
        "import venezuelan_beaver_cheese",
    )
    rule_runner.add_to_build_file("src/python", "python_sources()")

    def run_dep_inference(
        address: Address,
        unowned_dependency_behavior: str,
    ) -> InferredDependencies:
        rule_runner.set_options(
            [
                "--backend-packages=pants.backend.python",
                f"--python-infer-unowned-dependency-behavior={unowned_dependency_behavior}",
                "--source-root-patterns=src/python",
            ],
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [InferPythonImportDependencies(target[PythonSourceField])],
        )

    # First test with "warning"
    run_dep_inference(Address("src/python", relative_file_path="cheesey.py"), "warning")
    assert len(caplog.records) == 1
    assert "The following imports in src/python/cheesey.py have no owners:" in caplog.text
    assert "  * venezuelan_beaver_cheese" in caplog.text

    # Now test with "error"
    caplog.clear()
    with pytest.raises(ExecutionError) as exc_info:
        run_dep_inference(Address("src/python", relative_file_path="cheesey.py"), "error")

    assert isinstance(exc_info.value.wrapped_exceptions[0], UnownedDependencyError)
    assert len(caplog.records) == 2  # one for the error being raised and one for our message
    assert "The following imports in src/python/cheesey.py have no owners:" in caplog.text
    assert "  * venezuelan_beaver_cheese" in caplog.text

    caplog.clear()

    # All modes should be fine if the module is explictly declared as a requirement
    rule_runner.add_to_build_file(
        "src/python",
        dedent(
            """\
                python_requirement(
                    name="venezuelan_beaver_cheese",
                    modules=["venezuelan_beaver_cheese"],
                    requirements=["venezuelan_beaver_cheese==1.0.0"],
                )
                python_sources(dependencies=[":venezuelan_beaver_cheese"])
            """
        ),
        overwrite=True,
    )
    for mode in UnownedDependencyUsage:
        run_dep_inference(Address("src/python", relative_file_path="cheesey.py"), mode.value)
        assert not caplog.records

    rule_runner.add_to_build_file("src/python", "python_sources()", overwrite=True)  # Cleanup

    # All modes should be fine if the module is implictly found via requirements.txt
    rule_runner.create_file("src/python/requirements.txt", "venezuelan_beaver_cheese==1.0.0")
    rule_runner.add_to_build_file(
        "src/python",
        dedent(
            """\
                python_requirements()
                python_sources()
            """
        ),
        overwrite=True,
    )
    for mode in UnownedDependencyUsage:
        run_dep_inference(Address("src/python", relative_file_path="cheesey.py"), mode.value)
        assert not caplog.records

    # All modes should be fine if the module is owned by a first party
    rule_runner.create_file("src/python/venezuelan_beaver_cheese.py")
    rule_runner.add_to_build_file("src/python", "python_sources()", overwrite=True)
    for mode in UnownedDependencyUsage:
        run_dep_inference(Address("src/python", relative_file_path="cheesey.py"), mode.value)
        assert not caplog.records
