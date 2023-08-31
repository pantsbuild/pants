# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.util_rules.package_dists import SetupKwargs, SetupKwargsRequest
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalTool,
    ExternalToolRequest,
)
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.options_parsing import _Options
from pants.engine.internals.session import SessionValues
from pants.engine.rules import Get, collect_rules, goal_rule, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.option.alias import CliAlias
from pants.option.config import Config
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.strutil import softwrap
from pants.version import VERSION


class PantsSetupKwargsRequest(SetupKwargsRequest):
    @classmethod
    def is_applicable(cls, _: Target) -> bool:
        # We always use our custom `setup()` kwargs generator for `python_distribution` targets in
        # this repo.
        return True


@rule
async def pants_setup_kwargs(request: PantsSetupKwargsRequest) -> SetupKwargs:
    kwargs = request.explicit_kwargs.copy()

    if request.target.address.path_safe_spec.startswith("testprojects"):
        return SetupKwargs(kwargs, address=request.target.address)

    # Validate that required fields are set.
    if not kwargs["name"].startswith("pantsbuild.pants"):
        raise ValueError(
            f"Invalid `name` kwarg in the `provides` field for {request.target.address}. The name "
            f"must start with 'pantsbuild.pants', but was {kwargs['name']}."
        )
    if "description" not in kwargs:
        raise ValueError(
            f"Missing a `description` kwarg in the `provides` field for {request.target.address}."
        )

    # Add classifiers. We preserve any that were already set.
    standard_classifiers = [
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Topic :: Software Development :: Build Tools",
    ]
    kwargs["classifiers"] = [*standard_classifiers, *kwargs.get("classifiers", [])]

    # Hardcode certain kwargs and validate that they weren't already set.
    hardcoded_kwargs = dict(
        version=VERSION,
        long_description=softwrap(
            """
            Pants is an Apache2 licensed build tool written in Python and Rust.

            The latest documentation can be found at [pantsbuild.org](https://www.pantsbuild.org/).
            """
        ),
        long_description_content_type="text/markdown",
        url="https://github.com/pantsbuild/pants",
        project_urls={
            "Documentation": "https://www.pantsbuild.org/",
            "Source": "https://github.com/pantsbuild/pants",
            "Tracker": "https://github.com/pantsbuild/pants/issues",
            "Changelog": "https://www.pantsbuild.org/docs/changelog",
            "Twitter": "https://twitter.com/pantsbuild",
            "Slack": "https://www.pantsbuild.org/docs/getting-help",
            "YouTube": "https://www.youtube.com/channel/UCCcfCbDqtqlCkFEuENsHlbQ",
            "Mailing lists": "https://www.pantsbuild.org/docs/getting-help",
        },
        license="Apache License, Version 2.0",
        zip_safe=True,
    )
    conflicting_hardcoded_kwargs = set(kwargs.keys()).intersection(hardcoded_kwargs.keys())
    if conflicting_hardcoded_kwargs:
        raise ValueError(
            f"These kwargs should not be set in the `provides` field for {request.target.address} "
            "because Pants's internal plugin will automatically set them: "
            f"{sorted(conflicting_hardcoded_kwargs)}"
        )
    kwargs.update(hardcoded_kwargs)

    return SetupKwargs(kwargs, address=request.target.address)


class CheckDefaultToolsSubsystem(GoalSubsystem):
    name = "check-default-tools"
    help = "Options for checking that external tool default locations are correctly typed."


class CheckDefaultTools(Goal):
    subsystem_cls = CheckDefaultToolsSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@goal_rule
async def check_default_tools(
    console: Console,
    real_opts: _Options,
) -> CheckDefaultTools:
    # The real options know about all the registered tools.
    for scope, si in real_opts.options.known_scope_to_info.items():
        if si.subsystem_cls and issubclass(si.subsystem_cls, ExternalTool):
            tool_cls = si.subsystem_cls
            console.print_stdout(f"Checking {console.cyan(tool_cls.name)}:")
            for known_version in tool_cls.default_known_versions:
                version = tool_cls.decode_known_version(known_version)
                # Note that we don't want to use the real option values here - we want to
                # verify that the *defaults* aren't broken. However the get_request_for() method
                # requires an instance (since it can consult option values, including custom
                # options for specific tools, that we don't know about), so we construct a
                # default one, but we force the --version to the one we're checking (which will
                # typically be the same as the default version, but doesn't have to be, if the
                # tool provides default_known_versions for versions other than default_version).
                args = ("./pants", f"--{scope}-version={version.version}")
                blank_opts = await Get(
                    _Options,
                    SessionValues(
                        {
                            OptionsBootstrapper: OptionsBootstrapper(
                                tuple(), ("./pants",), args, Config(tuple()), CliAlias()
                            )
                        }
                    ),
                )
                instance = tool_cls(blank_opts.options.for_scope(scope))
                req = instance.get_request_for(version.platform, version.sha256, version.filesize)
                console.write_stdout(f"  version {version.version} for {version.platform}... ")
                # TODO: We'd like to run all the requests concurrently, but since we can't catch
                #  engine exceptions, we wouldn't have an easy way to output which one failed.
                await Get(DownloadedExternalTool, ExternalToolRequest, req)
                console.print_stdout(console.sigil_succeeded())
    return CheckDefaultTools(exit_code=0)


def rules():
    return (*collect_rules(), UnionRule(SetupKwargsRequest, PantsSetupKwargsRequest))
