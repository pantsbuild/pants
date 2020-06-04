# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path, PurePath
from typing import Callable, Dict, List, Optional, cast

from packaging.version import Version

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonLibrary,
    PythonLibrarySources,
    PythonProvidesField,
    PythonSources,
)
from pants.backend.python.targets.python_library import PythonLibrary as PythonLibraryV1
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.target import Target
from pants.subsystem.subsystem import Subsystem
from pants.util.ordered_set import FrozenOrderedSet
from pants.version import PANTS_SEMVER, VERSION


def pants_setup_py(
    name: str, description: str, additional_classifiers: Optional[List[str]] = None, **kwargs
) -> PythonArtifact:
    """Creates the setup_py for a Pants artifact.

    :param name: The name of the package.
    :param description: A brief description of what the package provides.
    :param additional_classifiers: Any additional trove classifiers that apply to the package,
                                        see: https://pypi.org/pypi?%3Aaction=list_classifiers
    :param kwargs: Any additional keyword arguments to be passed to `setuptools.setup
                   <https://pythonhosted.org/setuptools/setuptools.html>`_.
    :returns: A setup_py suitable for building and publishing Pants components.
    """
    if not name.startswith("pantsbuild.pants"):
        raise ValueError(
            f"Pants distribution package names must start with 'pantsbuild.pants', given {name}"
        )

    standard_classifiers = [
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        # We know for a fact these OSs work but, for example, know Windows
        # does not work yet.  Take the conservative approach and only list OSs
        # we know pants works with for now.
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Topic :: Software Development :: Build Tools",
    ]
    classifiers = FrozenOrderedSet(standard_classifiers + (additional_classifiers or []))

    notes = PantsReleases.global_instance().notes_for_version(PANTS_SEMVER)

    return PythonArtifact(
        name=name,
        version=VERSION,
        description=description,
        long_description=Path("src/python/pants/ABOUT.rst").read_text() + notes,
        long_description_content_type="text/x-rst",
        url="https://github.com/pantsbuild/pants",
        project_urls={
            "Documentation": "https://www.pantsbuild.org/",
            "Source": "https://github.com/pantsbuild/pants",
            "Tracker": "https://github.com/pantsbuild/pants/issues",
        },
        license="Apache License, Version 2.0",
        zip_safe=True,
        classifiers=list(classifiers),
        **kwargs,
    )


def contrib_setup_py_context_aware_object_factory(parse_context) -> Callable:
    def contrib_setup_py(
        name: str,
        description: str,
        build_file_aliases: bool = False,
        global_subsystems: bool = False,
        register_goals: bool = False,
        rules: bool = False,
        target_types: bool = False,
        additional_classifiers: Optional[List[str]] = None,
        **kwargs,
    ) -> PythonArtifact:
        """Creates the setup_py for a pants contrib plugin artifact.

        :param name: The name of the package; must start with 'pantsbuild.pants.contrib.'.
        :param description: A brief description of what the plugin provides.
        :param additional_classifiers: Any additional trove classifiers that apply to the plugin,
                                       see: https://pypi.org/pypi?%3Aaction=list_classifiers
        :param build_file_aliases: If `True`, register.py:build_file_aliases must be defined and
                                   registers the 'build_file_aliases' 'pantsbuild.plugin' entrypoint.
        :param global_subsystems: If `True`, register.py:global_subsystems must be defined and
                                  registers the 'global_subsystems' 'pantsbuild.plugin' entrypoint.
        :param register_goals: If `True`, register.py:register_goals must be defined and
                               registers the 'register_goals' 'pantsbuild.plugin' entrypoint.
        :param rules: If `True`, register.py:rules must be defined and registers the 'rules'
                      'pantsbuild.plugin' entrypoint.
        :param target_types: If `True`, register.py:target_types must be defined and registers
                             the 'target_types' 'pantsbuild.plugin' entrypoint.
        :param kwargs: Any additional keyword arguments to be passed to `setuptools.setup
                       <https://pythonhosted.org/setuptools/setuptools.html>`_.
        :returns: A setup_py suitable for building and publishing Pants components.
        """
        if not name.startswith("pantsbuild.pants.contrib."):
            raise ValueError(
                f"Contrib plugin package names must start with 'pantsbuild.pants.contrib.', given {name}"
            )

        setup_py = pants_setup_py(
            name,
            description,
            additional_classifiers=additional_classifiers,
            namespace_packages=["pants", "pants.contrib"],
            **kwargs,
        )

        if build_file_aliases or register_goals or global_subsystems or rules or target_types:
            rel_path = parse_context.rel_path
            # NB: We don't have proper access to SourceRoot computation here, but
            #
            #  we happen to know that:
            #  A) All existing contribs have their contrib_setup_py() invocation in a BUILD file
            #    exactly three path segments under the source root (i.e., they all have a source
            #    root of src/<name>src/python/, and are defined in pants/contrib/<name>/BUILD under
            #    that.)
            #  B) We are not adding any new contribs in the future, as this idiom is going away.
            #
            # So we can semi-hackily compute the register module using this knowledge.
            module = (
                PurePath(rel_path)
                .relative_to(PurePath(rel_path).parent.parent.parent)
                .as_posix()
                .replace("/", ".")
            )
            entry_points = []
            if build_file_aliases:
                entry_points.append(f"build_file_aliases = {module}.register:build_file_aliases")
            if register_goals:
                entry_points.append(f"register_goals = {module}.register:register_goals")
            if global_subsystems:
                entry_points.append(f"global_subsystems = {module}.register:global_subsystems")
            if rules:
                entry_points.append(f"rules = {module}.register:rules")
            if target_types:
                entry_points.append(f"target_types = {module}.register:target_types")

            setup_py.setup_py_keywords["entry_points"] = {"pantsbuild.plugin": entry_points}

        return setup_py

    return contrib_setup_py


class PantsReleases(Subsystem):
    """A subsystem to hold per-pants-release configuration."""

    options_scope = "pants-releases"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--branch-notes",
            type=dict,
            help="A dict from branch name to release notes rst-file location.",
        )

    @property
    def _branch_notes(self) -> Dict[str, str]:
        return cast(Dict[str, str], self.options.branch_notes)

    @classmethod
    def _branch_name(cls, version: Version) -> str:
        """Defines a mapping between versions and branches.

        All releases, including dev releases, map to a particular branch page.
        """
        suffix = version.public[len(version.base_version) :]
        components = version.base_version.split(".") + [suffix]
        if suffix != "" and not (suffix.startswith("rc") or suffix.startswith(".dev")):
            raise ValueError(f"Unparseable pants version number: {version}")
        return "{}.{}.x".format(*components[:2])

    def notes_for_version(self, version: Version) -> str:
        """Given the parsed Version of pants, return its release notes."""
        branch_name = self._branch_name(version)
        branch_notes_file = self._branch_notes.get(branch_name, None)
        if branch_notes_file is None:
            raise ValueError(
                f"Version {version} lives in branch {branch_name}, which is not configured in "
                f"{self._branch_notes}."
            )
        return Path(branch_notes_file).read_text()


class ContribPluginV1(PythonLibraryV1):
    pass


class ContribPluginSources(PythonSources):
    default = ("register.py",)


class ContribPluginProvidesField(PythonProvidesField):
    required = True


class ContribPlugin(Target):
    alias = "contrib_plugin"
    core_fields = (
        *(
            FrozenOrderedSet(PythonLibrary.core_fields)  # type: ignore[misc]
            - {PythonLibrarySources, PythonProvidesField}
        ),
        ContribPluginSources,
        ContribPluginProvidesField,
    )


def global_subsystems():
    return {PantsReleases}


def build_file_aliases():
    return BuildFileAliases(
        context_aware_object_factories={
            "contrib_setup_py": contrib_setup_py_context_aware_object_factory
        },
        objects={"pants_setup_py": pants_setup_py},
        targets={"contrib_plugin": ContribPluginV1},
    )


def target_types():
    return [ContribPlugin]
