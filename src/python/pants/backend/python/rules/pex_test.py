# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
import zipfile
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple, cast

import pytest
from pkg_resources import Requirement

from pants.backend.python.rules import download_pex_bin
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexPlatforms,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.pex import rules as pex_rules
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.target_types import PythonInterpreterCompatibility
from pants.engine.addresses import Address
from pants.engine.fs import Digest, DirectoryToMaterialize, FileContent, InputFilesContent
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import FieldSet
from pants.python.python_setup import PythonSetup
from pants.testutil.engine.util import create_subsystem
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.subsystem.util import init_subsystem
from pants.util.frozendict import FrozenDict
from pants.util.strutil import create_path_env_var


def test_merge_interpreter_constraints() -> None:
    def assert_merged(*, input: List[List[str]], expected: List[str]) -> None:
        assert PexInterpreterConstraints.merge_constraint_sets(input) == expected

    # Multiple constraint sets get merged so that they are ANDed.
    # A & B => A & B
    assert_merged(
        input=[["CPython==2.7.*"], ["CPython==3.6.*"]], expected=["CPython==2.7.*,==3.6.*"]
    )

    # Multiple constraints within a single constraint set are kept separate so that they are ORed.
    # A | B => A | B
    assert_merged(
        input=[["CPython==2.7.*", "CPython==3.6.*"]], expected=["CPython==2.7.*", "CPython==3.6.*"]
    )

    # Input constraints already were ANDed.
    # A => A
    assert_merged(input=[["CPython>=2.7,<3"]], expected=["CPython>=2.7,<3"])

    # Both AND and OR.
    # (A | B) & C => (A & B) | (B & C)
    assert_merged(
        input=[["CPython>=2.7,<3", "CPython>=3.5"], ["CPython==3.6.*"]],
        expected=["CPython>=2.7,<3,==3.6.*", "CPython>=3.5,==3.6.*"],
    )
    # A & B & (C | D) => (A & B & C) | (A & B & D)
    assert_merged(
        input=[["CPython==2.7.*"], ["CPython==3.6.*"], ["CPython==3.7.*", "CPython==3.8.*"]],
        expected=["CPython==2.7.*,==3.6.*,==3.7.*", "CPython==2.7.*,==3.6.*,==3.8.*"],
    )
    # (A | B) & (C | D) => (A & C) | (A & D) | (B & C) | (B & D)
    assert_merged(
        input=[["CPython>=2.7,<3", "CPython>=3.5"], ["CPython==3.6.*", "CPython==3.7.*"]],
        expected=[
            "CPython>=2.7,<3,==3.6.*",
            "CPython>=2.7,<3,==3.7.*",
            "CPython>=3.5,==3.6.*",
            "CPython>=3.5,==3.7.*",
        ],
    )
    # A & (B | C | D) & (E | F) & G =>
    # (A & B & E & G) | (A & B & F & G) | (A & C & E & G) | (A & C & F & G) | (A & D & E & G) | (A & D & F & G)
    assert_merged(
        input=[
            ["CPython==3.6.5"],
            ["CPython==2.7.14", "CPython==2.7.15", "CPython==2.7.16"],
            ["CPython>=3.6", "CPython==3.5.10"],
            ["CPython>3.8"],
        ],
        expected=[
            "CPython==2.7.14,==3.5.10,==3.6.5,>3.8",
            "CPython==2.7.14,>=3.6,==3.6.5,>3.8",
            "CPython==2.7.15,==3.5.10,==3.6.5,>3.8",
            "CPython==2.7.15,>=3.6,==3.6.5,>3.8",
            "CPython==2.7.16,==3.5.10,==3.6.5,>3.8",
            "CPython==2.7.16,>=3.6,==3.6.5,>3.8",
        ],
    )

    # Deduplicate between constraint_sets
    # (A | B) & (A | B) => A | B. Naively, this should actually resolve as follows:
    #   (A | B) & (A | B) => (A & A) | (A & B) | (B & B) => A | (A & B) | B.
    # But, we first deduplicate each constraint_set.  (A | B) & (A | B) can be rewritten as
    # X & X => X.
    assert_merged(
        input=[["CPython==2.7.*", "CPython==3.6.*"], ["CPython==2.7.*", "CPython==3.6.*"]],
        expected=["CPython==2.7.*", "CPython==3.6.*"],
    )
    # (A | B) & C & (A | B) => (A & C) | (B & C). Alternatively, this can be rewritten as
    # X & Y & X => X & Y.
    assert_merged(
        input=[
            ["CPython>=2.7,<3", "CPython>=3.5"],
            ["CPython==3.6.*"],
            ["CPython>=3.5", "CPython>=2.7,<3"],
        ],
        expected=["CPython>=2.7,<3,==3.6.*", "CPython>=3.5,==3.6.*"],
    )

    # No specifiers
    assert_merged(input=[["CPython"]], expected=["CPython"])
    assert_merged(input=[["CPython"], ["CPython==3.7.*"]], expected=["CPython==3.7.*"])

    # No interpreter is shorthand for CPython, which is how Pex behaves
    assert_merged(input=[[">=3.5"], ["CPython==3.7.*"]], expected=["CPython>=3.5,==3.7.*"])

    # Different Python interpreters, which are guaranteed to fail when ANDed but are safe when ORed.
    with pytest.raises(ValueError):
        PexInterpreterConstraints.merge_constraint_sets([["CPython==3.7.*"], ["PyPy==43.0"]])
    assert_merged(
        input=[["CPython==3.7.*", "PyPy==43.0"]], expected=["CPython==3.7.*", "PyPy==43.0"]
    )

    # Ensure we can handle empty input.
    assert_merged(input=[], expected=[])


@dataclass(frozen=True)
class MockFieldSet(FieldSet):
    compatibility: PythonInterpreterCompatibility

    @classmethod
    def create_for_test(cls, address: str, compat: Optional[str]) -> "MockFieldSet":
        addr = Address.parse(address)
        return cls(address=addr, compatibility=PythonInterpreterCompatibility(compat, address=addr))


def test_group_field_sets_by_constraints() -> None:
    py2_fs = MockFieldSet.create_for_test("//:py2", ">=2.7,<3")
    py3_fs = [
        MockFieldSet.create_for_test("//:py3", "==3.6.*"),
        MockFieldSet.create_for_test("//:py3_second", "==3.6.*"),
    ]
    no_constraints_fs = MockFieldSet.create_for_test("//:no_constraints", None)
    assert PexInterpreterConstraints.group_field_sets_by_constraints(
        [py2_fs, *py3_fs, no_constraints_fs],
        python_setup=create_subsystem(PythonSetup, interpreter_constraints=[]),
    ) == FrozenDict(
        {
            PexInterpreterConstraints(): (no_constraints_fs,),
            PexInterpreterConstraints(["CPython>=2.7,<3"]): (py2_fs,),
            PexInterpreterConstraints(["CPython==3.6.*"]): tuple(py3_fs),
        }
    )


@dataclass(frozen=True)
class ExactRequirement:
    project_name: str
    version: str

    @classmethod
    def parse(cls, requirement: str) -> "ExactRequirement":
        req = Requirement.parse(requirement)
        assert len(req.specs) == 1, (
            "Expected an exact requirement with only 1 specifier, given {requirement} with "
            "{count} specifiers".format(requirement=requirement, count=len(req.specs))
        )
        operator, version = req.specs[0]
        assert operator == "==", (
            "Expected an exact requirement using only the '==' specifier, given {requirement} "
            "using the {operator!r} operator".format(requirement=requirement, operator=operator)
        )
        return cls(project_name=req.project_name, version=version)


def parse_requirements(requirements: Iterable[str]) -> Iterator[ExactRequirement]:
    for requirement in requirements:
        yield ExactRequirement.parse(requirement)


class PexTest(ExternalToolTestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *pex_rules(),
            *download_pex_bin.rules(),
            *python_native_code.rules(),
            *subprocess_environment.rules(),
            RootRule(PexRequest),
        )

    def create_pex_and_get_all_data(
        self,
        *,
        requirements=PexRequirements(),
        entry_point=None,
        interpreter_constraints=PexInterpreterConstraints(),
        platforms=PexPlatforms(),
        sources: Optional[Digest] = None,
        additional_inputs: Optional[Digest] = None,
        additional_pants_args: Tuple[str, ...] = (),
        additional_pex_args: Tuple[str, ...] = (),
    ) -> Dict:
        request = PexRequest(
            output_filename="test.pex",
            requirements=requirements,
            interpreter_constraints=interpreter_constraints,
            platforms=platforms,
            entry_point=entry_point,
            sources=sources,
            additional_inputs=additional_inputs,
            additional_args=additional_pex_args,
        )
        pex = self.request_single_product(
            Pex,
            Params(
                request,
                create_options_bootstrapper(
                    args=["--backend-packages2=pants.backend.python", *additional_pants_args]
                ),
            ),
        )
        self.scheduler.materialize_directory(DirectoryToMaterialize(pex.digest))
        pex_path = os.path.join(self.build_root, "test.pex")
        with zipfile.ZipFile(pex_path, "r") as zipfp:
            with zipfp.open("PEX-INFO", "r") as pex_info:
                pex_info_content = pex_info.readline().decode()
                pex_list = zipfp.namelist()
        return {
            "pex": pex,
            "local_path": pex_path,
            "info": json.loads(pex_info_content),
            "files": pex_list,
        }

    def create_pex_and_get_pex_info(
        self,
        *,
        requirements=PexRequirements(),
        entry_point=None,
        interpreter_constraints=PexInterpreterConstraints(),
        platforms=PexPlatforms(),
        sources: Optional[Digest] = None,
        additional_pants_args: Tuple[str, ...] = (),
        additional_pex_args: Tuple[str, ...] = (),
    ) -> Dict:
        return cast(
            Dict,
            self.create_pex_and_get_all_data(
                requirements=requirements,
                entry_point=entry_point,
                interpreter_constraints=interpreter_constraints,
                platforms=platforms,
                sources=sources,
                additional_pants_args=additional_pants_args,
                additional_pex_args=additional_pex_args,
            )["info"],
        )

    def test_pex_execution(self) -> None:
        sources_content = InputFilesContent(
            (
                FileContent(path="main.py", content=b'print("from main")'),
                FileContent(path="subdir/sub.py", content=b'print("from sub")'),
            )
        )

        sources = self.request_single_product(Digest, sources_content)
        pex_output = self.create_pex_and_get_all_data(entry_point="main", sources=sources)

        pex_files = pex_output["files"]
        assert "pex" not in pex_files
        assert "main.py" in pex_files
        assert "subdir/sub.py" in pex_files

        init_subsystem(PythonSetup)
        python_setup = PythonSetup.global_instance()
        env = {"PATH": create_path_env_var(python_setup.interpreter_search_paths)}

        process = Process(
            argv=("python", "test.pex"),
            env=env,
            input_digest=pex_output["pex"].digest,
            description="Run the pex and make sure it works",
        )
        result = self.request_single_product(ProcessResult, process)
        assert result.stdout == b"from main\n"

    def test_resolves_dependencies(self) -> None:
        requirements = PexRequirements(["six==1.12.0", "jsonschema==2.6.0", "requests==2.23.0"])
        pex_info = self.create_pex_and_get_pex_info(requirements=requirements)
        # NB: We do not check for transitive dependencies, which PEX-INFO will include. We only check
        # that at least the dependencies we requested are included.
        assert set(parse_requirements(requirements)).issubset(
            set(parse_requirements(pex_info["requirements"]))
        )

    def test_requirement_constraints(self) -> None:
        # This is intentionally old; a constraint will resolve us to a more modern version.
        direct_dep = "requests==1.0.0"
        constraints = [
            "requests==2.23.0",
            "certifi==2019.6.16",
            "chardet==3.0.2",
            "idna==2.7",
            "urllib3==1.25.6",
        ]
        self.create_file("constraints.txt", "\n".join(constraints))

        pex_info = self.create_pex_and_get_pex_info(
            requirements=PexRequirements([direct_dep]),
            additional_pants_args=("--python-setup-requirement-constraints=constraints.txt",),
        )
        assert set(parse_requirements(pex_info["requirements"])) == set(
            parse_requirements(constraints)
        )

    def test_entry_point(self) -> None:
        entry_point = "pydoc"
        pex_info = self.create_pex_and_get_pex_info(entry_point=entry_point)
        assert pex_info["entry_point"] == entry_point

    def test_interpreter_constraints(self) -> None:
        constraints = PexInterpreterConstraints(["CPython>=2.7,<3", "CPython>=3.6"])
        pex_info = self.create_pex_and_get_pex_info(interpreter_constraints=constraints)
        assert set(pex_info["interpreter_constraints"]) == set(constraints)

    def test_additional_args(self) -> None:
        pex_info = self.create_pex_and_get_pex_info(additional_pex_args=("--not-zip-safe",))
        assert pex_info["zip_safe"] is False

    def test_platforms(self) -> None:
        # We use Python 2.7, rather than Python 3, to ensure that the specified platform is
        # actually used.
        platforms = PexPlatforms(["linux-x86_64-cp-27-cp27mu"])
        constraints = PexInterpreterConstraints(["CPython>=2.7,<3", "CPython>=3.6"])
        pex_output = self.create_pex_and_get_all_data(
            requirements=PexRequirements(["cryptography==2.9"]),
            platforms=platforms,
            interpreter_constraints=constraints,
        )
        assert any(
            "cryptography-2.9-cp27-cp27mu-manylinux2010_x86_64.whl" in fp
            for fp in pex_output["files"]
        )
        assert not any("cryptography-2.9-cp27-cp27m-" in fp for fp in pex_output["files"])
        assert not any("cryptography-2.9-cp35-abi3" in fp for fp in pex_output["files"])

        # NB: Platforms override interpreter constraints.
        assert pex_output["info"]["interpreter_constraints"] == []

    def test_additional_inputs(self) -> None:
        # We use pex's --preamble-file option to set a custom preamble from a file.
        # This verifies that the file was indeed provided as additional input to the pex call.
        preamble_file = "custom_preamble.txt"
        preamble = "#!CUSTOM PREAMBLE\n"
        additional_inputs_content = InputFilesContent(
            (FileContent(path=preamble_file, content=preamble.encode()),)
        )
        additional_inputs = self.request_single_product(Digest, additional_inputs_content)
        additional_pex_args = (f"--preamble-file={preamble_file}",)
        pex_output = self.create_pex_and_get_all_data(
            additional_inputs=additional_inputs, additional_pex_args=additional_pex_args
        )
        with zipfile.ZipFile(pex_output["local_path"], "r") as zipfp:
            with zipfp.open("__main__.py", "r") as main:
                main_content = main.read().decode()
        assert main_content[: len(preamble)] == preamble
