# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from packaging.version import Version

from pants.backend.python.goals.setup_py import SetupKwargs, SetupKwargsRequest
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.version import PANTS_SEMVER, VERSION


class PantsReleases(Subsystem):
    """Options for Pants's release process."""

    options_scope = "pants-releases"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--release-notes",
            type=dict,
            help="A dict from branch name to release notes rst-file location.",
        )

    @property
    def _release_notes(self) -> FrozenDict[str, str]:
        return FrozenDict(self.options.release_notes)

    @classmethod
    def _branch_name(cls, version: Version) -> str:
        """Defines a mapping between versions and branches.

        All releases, including dev releases, map to a particular branch page.
        """
        suffix = version.public[len(version.base_version) :]
        components = version.base_version.split(".") + [suffix]
        if suffix != "" and not (
            suffix.startswith("rc") or suffix.startswith("a") or suffix.startswith(".dev")
        ):
            raise ValueError(f"Unparseable pants version number: {version}")
        return "{}.{}.x".format(*components[:2])

    def notes_file_for_version(self, version: Version) -> str:
        """Given the parsed Version of Pants, return its release notes file path."""
        branch_name = self._branch_name(version)
        notes_file = self._release_notes.get(branch_name)
        if notes_file is None:
            raise ValueError(
                f"Version {version} lives in branch {branch_name}, which is not configured in "
                f"{self._release_notes}."
            )
        return notes_file


class PantsSetupKwargsRequest(SetupKwargsRequest):
    @classmethod
    def is_applicable(cls, _: Target) -> bool:
        # We always use our custom `setup()` kwargs generator for `python_distribution` targets in
        # this repo.
        return True


@rule
async def pants_setup_kwargs(
    request: PantsSetupKwargsRequest, pants_releases: PantsReleases
) -> SetupKwargs:
    kwargs = request.explicit_kwargs.copy()

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

    # Determine the long description by reading from ABOUT.rst and the release notes.
    notes_file = pants_releases.notes_file_for_version(PANTS_SEMVER)
    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            ["src/python/pants/ABOUT.rst", notes_file],
            description_of_origin="Pants release files",
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
        ),
    )
    long_description = "\n".join(file_content.content.decode() for file_content in digest_contents)

    # Hardcode certain kwargs and validate that they weren't already set.
    hardcoded_kwargs = dict(
        version=VERSION,
        long_description=long_description,
        long_description_content_type="text/x-rst",
        url="https://github.com/pantsbuild/pants",
        project_urls={
            "Documentation": "https://www.pantsbuild.org/",
            "Source": "https://github.com/pantsbuild/pants",
            "Tracker": "https://github.com/pantsbuild/pants/issues",
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


def rules():
    return (*collect_rules(), UnionRule(SetupKwargsRequest, PantsSetupKwargsRequest))
