# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.base.deprecated import resolve_conflicting_options
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap


class PythonRepos(Subsystem):
    options_scope = "python-repos"
    help = softwrap(
        """
        External Python code repositories, such as PyPI.

        These options may be used to point to custom package indexes when resolving requirements.
        """
    )

    pypi_index = "https://pypi.org/simple/"

    _find_links = StrListOption(
        help=softwrap(
            """
            URLs and/or file paths corresponding to pip's `--find-links` option.

            Per [pip's documentation](https://pip.pypa.io/en/stable/cli/pip_wheel/?highlight=find%20links#cmdoption-f),
            URLs should be to HTML files with links to `.whl` and/or
            sdist files. Local paths must be absolute, and can either be to an HTML file with
            links or to a directory with `.whl` and/or sdist files, e.g.
            `file:///Users/pantsbuild/prebuilt_wheels`.

            For local paths, you may want to use the option `[python-repos].path_mappings`.
            """
        )
    )
    _repos = StrListOption(
        help=softwrap(
            """
            URLs of code repositories to look for requirements. In Pip and Pex, this option
            corresponds to the `--find-links` option.
            """
        ),
        advanced=True,
        removal_version="3.0.0.dev0",
        removal_hint="A deprecated alias for `[python-repos].find_links`.",
    )
    indexes = StrListOption(
        default=[pypi_index],
        help=softwrap(
            """
            URLs of [PEP-503 compatible](https://peps.python.org/pep-0503/) code repository
            indexes to look for requirements.

            If set to an empty list, then Pex will use no indexes (meaning it will not use PyPI).
            """
        ),
        advanced=True,
    )

    path_mappings = StrListOption(
        help=softwrap(
            f"""
            Mappings to facilitate using local Python requirements when the absolute file paths
            are different on different users' machines. For example, the
            path `file:///Users/pantsbuild/prebuilt_wheels/django-3.1.1-py3-none-any.whl` could
            become `file://${{WHEELS_DIR}}/django-3.1.1-py3-none-any.whl`, where each user can
            configure what WHEELS_DIR points to on their machine.

            Expects values in the form `NAME|PATH`. You can specify multiple entries in the list.

            Typically, this setting will be different for each user because paths may differ on
            their machine. So, we usually recommend setting this option via a `.pants.rc`
            file ({doc_url('options#pantsrc-file')} or the environment variable
            `PANTS_PYTHON_REPOS_PATH_MAPPINGS`.

            When using `[python-repos].find_links`, you must still use a valid absolute path for
            the current machine. See
            {doc_url("python-third-party-dependencies#local-requirements")}.

            Note: Only takes effect if you use Pex lockfiles. Use the default
            `[python].lockfile_generator = "pex"` and run the `generate-lockfiles` goal.
            """
        ),
        advanced=True,
    )

    @property
    def find_links(self) -> tuple[str, ...]:
        return cast(
            "tuple[str, ...]",
            resolve_conflicting_options(
                old_option="repos",
                new_option="find_links",
                old_scope=self.options_scope,
                new_scope=self.options_scope,
                old_container=self.options,
                new_container=self.options,
            ),
        )
