# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Optional

from pants.backend.python.rules import pex_from_targets, python_sources
from pants.backend.python.rules.pex import PexRequest, PexRequirements
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import PythonSourceFilesRequest
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.build_graph.address import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import RootRule, SubsystemRule
from pants.python.python_setup import PythonSetup, ResolveAllConstraintsOption
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PexTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *pex_from_targets.rules(),
            *python_sources.rules(),
            RootRule(PexFromTargetsRequest),
            RootRule(PythonSourceFilesRequest),
            SubsystemRule(PythonSetup),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary]

    def test_constraints_validation(self) -> None:

        self.add_to_build_file(
            "",
            dedent(
                """
                python_requirement_library(name="foo", requirements=["foo-bar>=0.1.2"])
                python_requirement_library(name="bar", requirements=["bar==5.5.5"])
                python_requirement_library(name="baz", requirements=["baz"])
                python_library(name="tgt", sources=[], dependencies=[":foo", ":bar", ":baz"])
                """
            ),
        )
        self.create_file(
            "constraints1.txt",
            dedent(
                """
                Foo._-BAR==1.0.0
                bar==5.5.5
                baz==2.2.2
                qux==3.4.5
            """
            ),
        )
        self.create_file(
            "constraints2.txt",
            dedent(
                """
                foo==1.0.0
                bar==5.5.5
                qux==3.4.5
            """
            ),
        )

        request = PexFromTargetsRequest(
            [Address.parse("//:tgt")], output_filename="demo.pex", internal_only=True
        )

        def get_pex_request(
            constraints_file: Optional[str], resolve_all: Optional[ResolveAllConstraintsOption]
        ) -> PexRequest:
            args = [
                "--backend-packages=pants.backend.python",
            ]
            if resolve_all:
                args.append(f"--python-setup-resolve-all-constraints={resolve_all.value}")
            if constraints_file:
                args.append(f"--python-setup-requirement-constraints={constraints_file}")
            return self.request_single_product(
                PexRequest, Params(request, create_options_bootstrapper(args=args))
            )

        pex_req1 = get_pex_request("constraints1.txt", ResolveAllConstraintsOption.NEVER)
        assert pex_req1.requirements == PexRequirements(["foo-bar>=0.1.2", "bar==5.5.5", "baz"])

        pex_req2 = get_pex_request("constraints1.txt", ResolveAllConstraintsOption.ALWAYS)
        assert pex_req2.requirements == PexRequirements(
            ["Foo._-BAR==1.0.0", "bar==5.5.5", "baz==2.2.2", "qux==3.4.5"]
        )

        with self.assertRaises(ExecutionError) as err:
            get_pex_request(None, ResolveAllConstraintsOption.ALWAYS)
        assert len(err.exception.wrapped_exceptions) == 1
        assert isinstance(err.exception.wrapped_exceptions[0], ValueError)
        assert (
            "[python-setup].resolve_all_constraints is set to always, so "
            "[python-setup].requirement_constraints must also be provided."
        ) in str(err.exception)

        # Shouldn't error, as we don't explicitly set --resolve-all-constraints.
        get_pex_request(None, None)
