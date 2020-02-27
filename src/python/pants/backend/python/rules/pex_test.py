# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
import zipfile
from typing import Dict, Optional, Tuple, cast

from pants.backend.python.rules import download_pex_bin
from pants.backend.python.rules.pex import (
    CreatePex,
    Pex,
    PexInterpreterConstraints,
    PexRequirements,
)
from pants.backend.python.rules.pex import rules as pex_rules
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.engine.fs import Digest, DirectoryToMaterialize, FileContent, InputFilesContent
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.python.python_setup import PythonSetup
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase
from pants.util.strutil import create_path_env_var


class PexTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *pex_rules(),
            *download_pex_bin.rules(),
            *python_native_code.rules(),
            *subprocess_environment.rules(),
            RootRule(CreatePex),
        )

    def create_pex_and_get_all_data(
        self,
        *,
        requirements=PexRequirements(),
        entry_point=None,
        interpreter_constraints=PexInterpreterConstraints(),
        input_files: Optional[Digest] = None,
        additional_pants_args: Tuple[str, ...] = (),
        additional_pex_args: Tuple[str, ...] = (),
    ) -> Dict:
        request = CreatePex(
            output_filename="test.pex",
            requirements=requirements,
            interpreter_constraints=interpreter_constraints,
            entry_point=entry_point,
            input_files_digest=input_files,
            additional_args=additional_pex_args,
        )
        requirements_pex = self.request_single_product(
            Pex,
            Params(
                request,
                create_options_bootstrapper(
                    args=["--backend-packages2=pants.backend.python", *additional_pants_args]
                ),
            ),
        )
        self.scheduler.materialize_directory(
            DirectoryToMaterialize(requirements_pex.directory_digest),
        )
        with zipfile.ZipFile(os.path.join(self.build_root, "test.pex"), "r") as pex:
            with pex.open("PEX-INFO", "r") as pex_info:
                pex_info_content = pex_info.readline().decode()
                pex_list = pex.namelist()
        return {"pex": requirements_pex, "info": json.loads(pex_info_content), "files": pex_list}

    def create_pex_and_get_pex_info(
        self,
        *,
        requirements=PexRequirements(),
        entry_point=None,
        interpreter_constraints=PexInterpreterConstraints(),
        input_files: Optional[Digest] = None,
        additional_pants_args: Tuple[str, ...] = (),
        additional_pex_args: Tuple[str, ...] = (),
    ) -> Dict:
        return cast(
            Dict,
            self.create_pex_and_get_all_data(
                requirements=requirements,
                entry_point=entry_point,
                interpreter_constraints=interpreter_constraints,
                input_files=input_files,
                additional_pants_args=additional_pants_args,
                additional_pex_args=additional_pex_args,
            )["info"],
        )

    def test_pex_execution(self) -> None:
        input_files_content = InputFilesContent(
            (
                FileContent(path="main.py", content=b'print("from main")'),
                FileContent(path="subdir/sub.py", content=b'print("from sub")'),
            )
        )

        input_files = self.request_single_product(Digest, input_files_content)
        pex_output = self.create_pex_and_get_all_data(entry_point="main", input_files=input_files)

        pex_files = pex_output["files"]
        self.assertTrue("pex" not in pex_files)
        self.assertTrue("main.py" in pex_files)
        self.assertTrue("subdir/sub.py" in pex_files)

        init_subsystem(PythonSetup)
        python_setup = PythonSetup.global_instance()
        env = {"PATH": create_path_env_var(python_setup.interpreter_search_paths)}

        req = ExecuteProcessRequest(
            argv=("python", "test.pex"),
            env=env,
            input_files=pex_output["pex"].directory_digest,
            description="Run the pex and make sure it works",
        )
        result = self.request_single_product(ExecuteProcessResult, req)
        self.assertEqual(result.stdout, b"from main\n")

    def test_resolves_dependencies(self) -> None:
        requirements = PexRequirements(
            requirements=("six==1.12.0", "jsonschema==2.6.0", "requests==2.23.0")
        )
        pex_info = self.create_pex_and_get_pex_info(requirements=requirements)
        # NB: We do not check for transitive dependencies, which PEX-INFO will include. We only check
        # that at least the dependencies we requested are included.
        assert set(requirements.requirements).issubset(pex_info["requirements"]) is True

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
            requirements=PexRequirements((direct_dep,)),
            additional_pants_args=("--python-setup-requirement-constraints=constraints.txt",),
        )
        assert set(pex_info["requirements"]) == set(constraints)

    def test_entry_point(self) -> None:
        entry_point = "pydoc"
        pex_info = self.create_pex_and_get_pex_info(entry_point=entry_point)
        assert pex_info["entry_point"] == entry_point

    def test_interpreter_constraints(self) -> None:
        constraints = PexInterpreterConstraints(constraint_set=("CPython>=2.7,<3", "CPython>=3.6"))
        pex_info = self.create_pex_and_get_pex_info(interpreter_constraints=constraints)
        assert set(pex_info["interpreter_constraints"]) == set(constraints.constraint_set)

    def test_additional_args(self) -> None:
        pex_info = self.create_pex_and_get_pex_info(additional_pex_args=("--not-zip-safe",))
        assert pex_info["zip_safe"] is False
