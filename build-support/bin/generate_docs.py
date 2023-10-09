# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generates and uploads the Pants reference documentation.

Dry run:

    ./pants run build-support/bin/generate_docs.py

Live run:

    ./pants run build-support/bin/generate_docs.py -- --sync --api-key=<API_KEY>

where API_KEY is your readme.io API Key, found here:
  https://dash.readme.com/project/pants/v2.6/api-key
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import pkgutil
import re
import subprocess
import textwrap
from pathlib import Path, PosixPath
from typing import Any, Dict, Iterable, cast

import chevron
from pants_release.common import die
from readme_api import DocRef, ReadmeAPI

from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.help.help_info_extracter import to_help_str
from pants.util.strutil import softwrap
from pants.version import MAJOR_MINOR

logger = logging.getLogger(__name__)

DOC_URL_RE = re.compile(
    r"https://www.pantsbuild.org/v(\d+\.[^/]+)/docs/(?P<slug>[a-zA-Z0-9_-]+)(?P<anchor>#[a-zA-Z0-9_-]+)?"
)


def main() -> None:
    logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)
    args = create_parser().parse_args()

    if args.sync and not args.api_key:
        raise Exception("You specified --sync so you must also specify --api-key")

    version = determine_pants_version(args.no_prompt)
    help_info = run_pants_help_all()
    slug_to_title = get_titles()
    help_info = rewrite_value_strs(help_info, slug_to_title)

    generator = ReferenceGenerator(args, version, help_info)
    if args.sync:
        generator.sync()
    else:
        generator.render()


def determine_pants_version(no_prompt: bool) -> str:
    version = MAJOR_MINOR
    if no_prompt:
        logger.info(f"Generating docs for Pants {version}.")
        return version

    key_confirmation = input(
        f"Generating docs for Pants {version}. Is this the correct version? [Y/n]: "
    )
    if key_confirmation and key_confirmation.lower() != "y":
        die(
            softwrap(
                """
                Please either `git checkout` to the appropriate branch (e.g. 2.1.x), or change
                src/python/pants/VERSION.
                """
            )
        )
    return version


# Code to replace doc urls with appropriate markdown, for rendering on the docsite.


def get_doc_slug(url: str) -> str:
    mo = DOC_URL_RE.match(url)
    if not mo:
        raise ValueError(f"Not a docsite URL: {url}")
    return cast(str, mo.group("slug"))


def find_doc_urls(strs: Iterable[str]) -> set[str]:
    """Find all the docsite urls in the given strings."""
    return {mo.group(0) for s in strs for mo in DOC_URL_RE.finditer(s)}


class DocUrlRewriter:
    def __init__(self, slug_to_title: dict[str, str]):
        self._slug_to_title = slug_to_title

    def _rewrite_url(self, mo: re.Match) -> str:
        # The docsite injects the version automatically at markdown rendering time, so we
        # must not also do so, or it will be doubled, and the resulting links will be broken.
        slug = mo.group("slug")
        anchor = mo.group("anchor") or ""
        title = self._slug_to_title.get(slug)
        if not title:
            raise ValueError(f"Found empty or no title for {mo.group(0)}")
        return f"[{title}](doc:{slug}{anchor})"

    def rewrite(self, s: str) -> str:
        return DOC_URL_RE.sub(self._rewrite_url, s)


def get_titles() -> dict[str, str]:
    """Return map from slug->title for each possible docsite reference."""
    result = {}
    for markdown_path in Path("docs/markdown").glob("**/*.md"):
        markdown_text = markdown_path.read_text()
        title_match = re.search(r'title: "(.*)"', markdown_text)
        assert title_match is not None
        slug_match = re.search(r'slug: "(.*)"', markdown_text)
        assert slug_match is not None
        result[slug_match[1]] = title_match[1]

    return result


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the Pants reference markdown files.")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        default=False,
        help="Don't prompt the user, accept defaults for all questions.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        default=False,
        help=softwrap(
            """
            Whether to sync the generated reference docs to the docsite.
            If unset, will generate markdown files to the path in --output
            instead.  If set, --api-key must be set.
            """
        ),
    )
    parser.add_argument(
        "--output",
        default=PosixPath(os.path.sep) / "tmp" / "pants_docs" / "help" / "option",
        type=Path,
        help=softwrap(
            """
            Path to a directory under which we generate the markdown files.
            Useful for viewing the files locally when testing and debugging
            the renderer.
            """
        ),
    )
    parser.add_argument("--api-key", help="The readme.io API key to use. Required for --sync.")
    return parser


def run_pants_help_all() -> dict[str, Any]:
    # List all (stable enough) backends here.
    backends = [
        "pants.backend.build_files.fix.deprecations",
        "pants.backend.build_files.fmt.black",
        "pants.backend.build_files.fmt.buildifier",
        "pants.backend.build_files.fmt.yapf",
        "pants.backend.awslambda.python",
        "pants.backend.codegen.protobuf.lint.buf",
        "pants.backend.codegen.protobuf.python",
        "pants.backend.codegen.thrift.apache.python",
        "pants.backend.docker",
        "pants.backend.docker.lint.hadolint",
        "pants.backend.experimental.adhoc",
        "pants.backend.experimental.codegen.protobuf.go",
        "pants.backend.experimental.codegen.protobuf.java",
        "pants.backend.experimental.codegen.protobuf.scala",
        "pants.backend.experimental.go",
        "pants.backend.experimental.helm",
        "pants.backend.experimental.java",
        "pants.backend.experimental.java.lint.google_java_format",
        "pants.backend.experimental.kotlin",
        "pants.backend.experimental.kotlin.lint.ktlint",
        "pants.backend.experimental.openapi",
        "pants.backend.experimental.openapi.lint.spectral",
        "pants.backend.experimental.python",
        "pants.backend.experimental.python.framework.stevedore",
        "pants.backend.experimental.python.lint.add_trailing_comma",
        "pants.backend.experimental.python.lint.ruff",
        "pants.backend.experimental.python.packaging.pyoxidizer",
        "pants.backend.experimental.python.typecheck.pytype",
        "pants.backend.experimental.scala",
        "pants.backend.experimental.scala.lint.scalafmt",
        "pants.backend.experimental.terraform",
        "pants.backend.experimental.tools.workunit_logger",
        "pants.backend.experimental.tools.yamllint",
        "pants.backend.google_cloud_function.python",
        "pants.backend.plugin_development",
        "pants.backend.python",
        "pants.backend.python.lint.autoflake",
        "pants.backend.python.lint.bandit",
        "pants.backend.python.lint.black",
        "pants.backend.python.lint.docformatter",
        "pants.backend.python.lint.flake8",
        "pants.backend.python.lint.isort",
        "pants.backend.python.lint.pydocstyle",
        "pants.backend.python.lint.pylint",
        "pants.backend.python.lint.pyupgrade",
        "pants.backend.python.lint.yapf",
        "pants.backend.python.mixed_interpreter_constraints",
        "pants.backend.python.typecheck.mypy",
        "pants.backend.shell",
        "pants.backend.shell.lint.shellcheck",
        "pants.backend.shell.lint.shfmt",
        "pants.backend.tools.preamble",
    ]
    argv = [
        "./pants",
        "--concurrent",
        "--plugins=[]",
        f"--backend-packages={repr(backends)}",
        "--no-verify-config",
        "help-all",
    ]
    run = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    try:
        run.check_returncode()
    except subprocess.CalledProcessError:
        logger.error(
            softwrap(
                f"""
                Running {argv} failed with exit code {run.returncode}.

                stdout:
                {textwrap.indent(run.stdout, " " * 4)}

                stderr:
                {textwrap.indent(run.stderr, " " * 4)}
                """
            )
        )
        raise
    return cast("dict[str, Any]", json.loads(run.stdout))


def value_strs_iter(help_info: dict[str, Any]) -> Iterable[str]:
    def _recurse(val: Any) -> Iterable[str]:
        if isinstance(val, str):
            yield val
        if isinstance(val, dict):
            for v in val.values():
                yield from _recurse(v)
        if isinstance(val, list):
            for v in val:
                yield from _recurse(v)

    yield from _recurse(help_info)


def rewrite_value_strs(help_info: dict[str, Any], slug_to_title: dict[str, str]) -> dict[str, Any]:
    """Return a copy of the argument with rewritten docsite URLs."""
    rewriter = DocUrlRewriter(slug_to_title)

    def _recurse(val: Any) -> Any:
        if isinstance(val, str):
            return rewriter.rewrite(val)
        if isinstance(val, dict):
            return {k: _recurse(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_recurse(x) for x in val]
        return val

    return cast("dict[str, Any]", _recurse(help_info))


class ReferenceGenerator:
    def __init__(self, args: argparse.Namespace, version: str, help_info: dict[str, Any]) -> None:
        self._args = args

        self._readme_api = ReadmeAPI(api_key=self._args.api_key, version=version)

        def get_tpl(name: str) -> str:
            # Note that loading relative to __name__ may not always work when __name__=='__main__'.
            buf = pkgutil.get_data("generate_docs", f"docs_templates/{name}")
            if buf is None:
                raise ValueError(f"No such template: {name}")
            return buf.decode()

        options_scope_tpl = get_tpl("options_scope_reference.md.mustache")
        single_option_tpl = get_tpl("single_option_reference.md.mustache")
        target_tpl = get_tpl("target_reference.md.mustache")
        self._renderer_args = {
            "partials_dict": {
                "scoped_options": options_scope_tpl,
                "single_option": single_option_tpl,
                "target": target_tpl,
            }
        }
        self._category_id: str | None = None  # Fetched lazily.

        # Load the data.
        self._options_info = self.process_options_input(help_info, sync=self._args.sync)
        self._targets_info = self.process_targets_input(help_info)

    @staticmethod
    def _link(scope: str, *, sync: bool) -> str:
        # docsite pages link to the slug, local pages to the .md source.
        url_safe_scope = scope.replace(".", "-")
        return f"reference-{url_safe_scope}" if sync else f"{url_safe_scope}.md"

    @classmethod
    def process_options_input(cls, help_info: dict[str, Any], *, sync: bool) -> dict:
        scope_to_help_info = help_info["scope_to_help_info"]

        # Process the list of consumed_scopes into a comma-separated list, and add it to the option
        # info for the goal's scope, to make it easy to render in the goal's options page.

        for goal, goal_info in help_info["name_to_goal_info"].items():
            assert isinstance(goal_info, dict)
            consumed_scopes = sorted(goal_info["consumed_scopes"])
            linked_consumed_scopes = [
                f"[{cs}]({cls._link(cs, sync=sync)})"
                for cs in consumed_scopes
                if cs and cs != goal_info["name"]
            ]
            comma_separated_consumed_scopes = ", ".join(linked_consumed_scopes)
            scope_to_help_info[goal][
                "comma_separated_consumed_scopes"
            ] = comma_separated_consumed_scopes

        # Process the option data.

        def munge_option(option_data):
            # Munge the default so we can display it nicely when it's multiline, while
            # still displaying it inline if it's not.
            default_help_repr = option_data.get("default_help_repr")
            if default_help_repr is None:
                default_str = to_help_str(option_data["default"])
            else:
                # It should already be a string, but might as well be safe.
                default_str = to_help_str(default_help_repr)
            # Some option defaults are paths under the buildroot, and we don't want the paths
            # of the environment in which we happened to run the doc generator to leak into the
            # published docs. So we replace with a placeholder string.
            default_str = default_str.replace(get_buildroot(), "<buildroot>")
            # Similarly, some option defaults are paths under the user's cache dir, so we replace
            # with a placeholder for the same reason.  Using $XDG_CACHE_HOME as the placeholder is
            # a useful hint to how the cache dir may be set, even though in practice the user may
            # not have this env var set. But googling XDG_CACHE_HOME will bring up documentation
            # of the ~/.cache fallback, so this seems like a sensible placeholder.
            default_str = default_str.replace(get_pants_cachedir(), "$XDG_CACHE_HOME")
            escaped_default_str = (
                html.escape(default_str, quote=False).replace("*", "&ast;").replace("_", "&lowbar;")
            )
            if "\n" in default_str:
                option_data["marked_up_default"] = f"<pre>{escaped_default_str}</pre>"
            else:
                option_data["marked_up_default"] = f"<code>{escaped_default_str}</code>"

        for shi in scope_to_help_info.values():
            for opt in shi["basic"]:
                munge_option(opt)
            for opt in shi["advanced"]:
                munge_option(opt)
            for opt in shi["deprecated"]:
                munge_option(opt)

        return help_info

    @classmethod
    def process_targets_input(cls, help_info: dict[str, Any]) -> dict[str, dict[str, Any]]:
        target_info = help_info["name_to_target_type_info"]
        for target in target_info.values():
            for field in target["fields"]:
                # Combine the `default` and `required` properties.
                default_str = (
                    html.escape(str(field["default"]))
                    .replace("*", "&ast;")
                    .replace("_", "&lowbar;")
                )
                field["default_or_required"] = (
                    "required" if field["required"] else f"default: <code>{default_str}</code>"
                )
                field["description"] = str(field["description"])
            target["fields"] = sorted(
                target["fields"], key=lambda fld: (-fld["required"], cast(str, fld["alias"]))
            )
            target["description"] = str(target["description"])

        return cast(Dict[str, Dict[str, Any]], target_info)

    @property
    def category_id(self) -> str:
        """The id of the "Reference" category on the docsite."""
        if self._category_id is None:
            self._category_id = self._readme_api.get_category("reference").id
        return self._category_id

    def _create(self, parent_doc_id: str | None, slug_suffix: str, title: str, body: str) -> None:
        """Create a new docsite reference page.

        Operates by creating a placeholder page, and then populating it via _update().

        This works around a quirk of the readme.io API: You cannot set the page slug when you
        create a page. Instead it is derived from the title.
        In fact there is no way to set or modify the slug via the API at all, which makes sense
        since the API references the page via the slug.  When you change the slug in the UI
        it is likely deleting and recreating the page under the covers.

        This is a problem if you want the slug to be different than the human-readable title,
        as we do in this case. Specifically, we want the human-readable page title to be just
        the scope name, e.g., `test` (so it appears that way in the sidebar). But we want the
        slug to be `reference-test`, so that it doesn't collide with any other, non-generated page
        that happens to occupy the slug `test`.

        To solve this we create the placeholder page with a title from which to derive the slug,
        and when we update the page to set its content, we update the title to be the
        one we want humans to see (this will not change the slug, see above).
        """
        slug = f"reference-{slug_suffix}"
        self._readme_api.create_doc(
            title=slug, category=self.category_id, parentDoc=parent_doc_id, hidden=False
        )

        # Placeholder page exists, now update it with the real title and body.
        self._readme_api.update_doc(slug=slug, title=title, category=self.category_id, body=body)

    def _render_target(self, alias: str) -> str:
        return cast(
            str, chevron.render("{{> target}}", self._targets_info[alias], **self._renderer_args)
        )

    def _render_options_body(self, scope_help_info: dict) -> str:
        """Renders the body of a single options help page."""
        return cast(
            str, chevron.render("{{> scoped_options}}", scope_help_info, **self._renderer_args)
        )

    @classmethod
    def _render_parent_page_body(cls, items: Iterable[str], *, sync: bool) -> str:
        """Returns the body of a parent page for the given items."""
        # The page just lists the items, with links to the page for each one.
        lines = [f"- [{item}]({cls._link(item, sync=sync)})" for item in items]
        return "\n".join(lines)

    def render(self) -> None:
        """Renders the pages to local disk.

        Useful for debugging and iterating on the markdown.
        """
        output_dir = Path(self._args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

        goals = [
            scope
            for scope, shi in self._options_info["scope_to_help_info"].items()
            if shi["is_goal"]
        ]
        subsystems = [
            scope
            for scope, shi in self._options_info["scope_to_help_info"].items()
            if scope and not shi["is_goal"]
        ]

        def write(filename: str, content: str) -> None:
            path = output_dir / filename
            path.write_text(content)
            logger.info(f"Wrote {path}")

        write("goals-index.md", self._render_parent_page_body(sorted(goals), sync=False))
        write("subsystems-index.md", self._render_parent_page_body(sorted(subsystems), sync=False))
        for shi in self._options_info["scope_to_help_info"].values():
            write(f"{shi['scope'] or 'GLOBAL'}.md", self._render_options_body(shi))

        write(
            "targets-index.md",
            self._render_parent_page_body(sorted(self._targets_info.keys()), sync=False),
        )
        for alias in self._targets_info.keys():
            write(f"{alias}.md", self._render_target(alias))

    def sync(self) -> None:
        """Render the pages and sync them to the live docsite.

        All pages live under the "reference" category.

        There are four top-level pages under that category:
        - Global options
        - The Goals parent page
        - The Subsystems parent page
        - The Targets parent page

        The individual reference pages are nested under these parent pages.
        """

        # Docs appear on the site in creation order.  If we only create new docs
        # that don't already exist then they will appear at the end, instead of in
        # alphabetical order. So we first delete all previous docs, then recreate them.
        #
        # TODO: Instead of deleting and recreating, we can set the order explicitly.
        #
        # Note that deleting a non-empty parent will fail, so we delete children first.
        def do_delete(docref: DocRef):
            for child in docref.children:
                do_delete(child)
            self._readme_api.delete_doc(docref.slug)

        docrefs = self._readme_api.get_docs_for_category("reference")

        for docref in docrefs:
            do_delete(docref)

        # Partition the scopes into goals and subsystems.
        goals = {}
        subsystems = {}
        for scope, shi in self._options_info["scope_to_help_info"].items():
            if scope == "":
                continue  # We handle the global scope separately.
            if shi["is_goal"]:
                goals[scope] = shi
            else:
                subsystems[scope] = shi

        # Create the top-level docs in order.
        self._create(
            parent_doc_id=None,
            slug_suffix="global",
            title="Global options",
            body=self._render_options_body(self._options_info["scope_to_help_info"][""]),
        )
        self._create(
            parent_doc_id=None,
            slug_suffix="all-goals",
            title="Goals",
            body=self._render_parent_page_body(sorted(goals.keys()), sync=True),
        )
        self._create(
            parent_doc_id=None,
            slug_suffix="all-subsystems",
            title="Subsystems",
            body=self._render_parent_page_body(sorted(subsystems.keys()), sync=True),
        )
        self._create(
            parent_doc_id=None,
            slug_suffix="all-targets",
            title="Targets",
            body=self._render_parent_page_body(sorted(self._targets_info.keys()), sync=True),
        )

        # Create the individual goal/subsystem/target docs.
        all_goals_doc_id = self._readme_api.get_doc("reference-all-goals").id
        for scope, shi in sorted(goals.items()):
            self._create(
                parent_doc_id=all_goals_doc_id,
                slug_suffix=scope,
                title=scope,
                body=self._render_options_body(shi),
            )

        all_subsystems_doc_id = self._readme_api.get_doc("reference-all-subsystems").id
        for scope, shi in sorted(subsystems.items()):
            self._create(
                parent_doc_id=all_subsystems_doc_id,
                slug_suffix=scope.replace(".", "-"),
                title=scope,
                body=self._render_options_body(shi),
            )

        all_targets_doc_id = self._readme_api.get_doc("reference-all-targets").id
        for alias, data in sorted(self._targets_info.items()):
            self._create(
                parent_doc_id=all_targets_doc_id,
                slug_suffix=alias,
                title=alias,
                body=self._render_target(alias),
            )


if __name__ == "__main__":
    main()
