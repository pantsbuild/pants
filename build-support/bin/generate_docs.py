# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generates and uploads the Pants reference documentation.

Dry run:

    ./pants run build-support/bin/generate_docs.py

Live run:

    ./pants run build-support/bin/generate_docs.py -- --sync --api-key=<API_KEY>

where API_KEY is your readme.io API Key, found here:
  https://dash.readme.com/project/pants/v2.0/api-key
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import pkgutil
import subprocess
from pathlib import Path, PosixPath
from typing import Any, Dict, Iterable, Optional, cast

import pystache
import requests
from common import die

from pants.help.help_info_extracter import to_help_str
from pants.version import MAJOR_MINOR

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)
    version = determine_pants_version()
    args = create_parser().parse_args()
    help_info = run_pants_help_all()
    generator = ReferenceGenerator(args, version, help_info)
    if args.sync:
        generator.sync()
    else:
        generator.render()


def determine_pants_version() -> str:
    version = MAJOR_MINOR
    key_confirmation = input(
        f"Generating docs for Pants {version}. Is this the correct version? [Y/n]: "
    )
    if key_confirmation and key_confirmation.lower() != "y":
        die(
            "Please either `git checkout` to the appropriate branch (e.g. 2.1.x), or change "
            "src/python/pants/VERSION."
        )
    return version


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the Pants reference markdown files.")
    parser.add_argument(
        "--sync",
        action="store_true",
        default=False,
        help="Whether to sync the generated reference docs to the docsite. "
        "If unset, will generate markdown files to the path in --output "
        "instead.  If set, --api-key must be set.",
    )
    parser.add_argument(
        "--output",
        default=PosixPath(os.path.sep) / "tmp" / "pants_docs" / "help" / "option",
        type=Path,
        help="Path to a directory under which we generate the markdown files. "
        "Useful for viewing the files locally when testing and debugging "
        "the renderer.",
    )
    parser.add_argument("--api-key", help="The readme.io API key to use. Required for --sync.")
    return parser


def run_pants_help_all() -> Dict:
    deactivated_backends = [
        "internal_plugins.releases",
        "toolchain.pants.auth",
        "toolchain.pants.buildsense",
        "toolchain.pants.common",
    ]
    activated_backends = ["pants.backend.python.lint.bandit", "pants.backend.python.lint.pylint"]
    argv = [
        "./pants",
        "--concurrent",
        f"--backend-packages=-[{', '.join(map(repr, deactivated_backends))}]",
        f"--backend-packages=+[{', '.join(map(repr, activated_backends))}]",
        "--no-verify-config",
        "help-all",
    ]
    run = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    try:
        run.check_returncode()
    except subprocess.CalledProcessError:
        logger.error(
            f"Running {argv} failed with exit code {run.returncode}.\n\nstdout:\n{run.stdout}"
            f"\n\nstderr:\n{run.stderr}"
        )
        raise
    return cast(Dict, json.loads(run.stdout))


class ReferenceGenerator:
    def __init__(self, args: argparse.Namespace, version: str, help_info: Dict) -> None:
        self._args = args
        self._version = version

        def get_tpl(name: str) -> str:
            # Note that loading relative to __name__ may not always work when __name__=='__main__'.
            buf = pkgutil.get_data("generate_docs", f"docs_templates/{name}")
            if buf is None:
                raise ValueError(f"No such template: {name}")
            return buf.decode()

        options_scope_tpl = get_tpl("options_scope_reference.md.mustache")
        single_option_tpl = get_tpl("single_option_reference.md.mustache")
        target_tpl = get_tpl("target_reference.md.mustache")
        self._renderer = pystache.Renderer(
            partials={
                "scoped_options": options_scope_tpl,
                "single_option": single_option_tpl,
                "target": target_tpl,
            }
        )
        self._category_id: Optional[str] = None  # Fetched lazily.

        # Load the data.
        self._options_info = self.process_options_input(help_info, sync=self._args.sync)
        self._targets_info = self.process_targets_input(help_info)

    @staticmethod
    def _link(scope: str, *, sync: bool) -> str:
        # docsite pages link to the slug, local pages to the .md source.
        return f"reference-{scope}" if sync else f"{scope}.md"

    @classmethod
    def process_options_input(cls, help_info: Dict, *, sync: bool) -> Dict:
        scope_to_help_info = help_info["scope_to_help_info"]

        # Process the list of consumed_scopes into a comma-separated list, and add it to the option
        # info for the goal's scope, to make it easy to render in the goal's options page.

        for goal, goal_info in help_info["name_to_goal_info"].items():
            consumed_scopes = sorted(goal_info["consumed_scopes"])
            linked_consumed_scopes = [
                f"[{cs}]({cls._link(cs, sync=sync)})" for cs in consumed_scopes if cs
            ]
            comma_separated_consumed_scopes = ", ".join(linked_consumed_scopes)
            scope_to_help_info[goal][
                "comma_separated_consumed_scopes"
            ] = comma_separated_consumed_scopes

        # Process the option data.

        def munge_option(option_data):
            # Munge the default so we can display it nicely when it's multiline, while
            # still displaying it inline if it's not.
            default_str = to_help_str(option_data["default"])
            escaped_default_str = html.escape(default_str, quote=False)
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
    def process_targets_input(cls, help_info: Dict) -> Dict[str, Dict[str, Any]]:
        target_info = help_info["name_to_target_type_info"]
        for target in target_info.values():
            for field in target["fields"]:
                # Combine the `default` and `required` properties.
                default_str = html.escape(str(field["default"]), quote=False)
                field["default_or_required"] = (
                    "required" if field["required"] else f"default: <code>{default_str}</code>"
                )
            target["fields"] = sorted(target["fields"], key=lambda fld: cast(str, fld["alias"]))

        return cast(Dict[str, Dict[str, Any]], target_info)

    @property
    def category_id(self) -> str:
        """The id of the "Reference" category on the docsite."""
        if self._category_id is None:
            self._category_id = self._get_id("categories/reference")
        return self._category_id

    def _access_readme_api(self, url_suffix: str, method: str, payload: str) -> Dict:
        """Sends requests to the readme.io API."""
        url = f"https://dash.readme.io/api/v1/{url_suffix}"
        headers = {"content-type": "application/json", "x-readme-version": f"v{self._version}"}
        response = requests.request(
            method, url, data=payload, headers=headers, auth=(self._args.api_key, "")
        )
        response.raise_for_status()
        return cast(Dict, response.json()) if response.text else {}

    def _create(
        self, parent_doc_id: Optional[str], slug_suffix: str, title: str, body: str
    ) -> None:
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

        logger.info(f"Creating {slug}")

        # See https://docs.readme.com/developers/reference/docs#createdoc.
        page = {
            "title": slug,
            "type": "basic",
            "body": "",
            "category": self.category_id,
            "parentDoc": parent_doc_id,
            "hidden": False,
        }
        payload = json.dumps(page)
        self._access_readme_api("docs/", "POST", payload)

        # Placeholder page exists, now update it with the real title and body.
        self._update(parent_doc_id, slug, title, body)

    def _update(self, parent_doc_id, slug, title, body):
        """Update an existing page."""

        logger.info(f"Updating {slug}")

        # See https://docs.readme.com/developers/reference/docs#updatedoc.
        page = {
            "title": title,
            "type": "basic",
            "body": body,
            "category": self.category_id,
            "parentDoc": parent_doc_id,
            "hidden": False,
        }
        payload = json.dumps(page)
        self._access_readme_api(f"docs/{slug}", "PUT", payload)

    def _delete(self, slug: str) -> None:
        """Delete an existing page."""

        logger.warning(f"Deleting {slug}")
        self._access_readme_api(f"docs/{slug}", "DELETE", "")

    def _get_id(self, url) -> str:
        """Returns the id of the entity at the specified readme.io API url."""
        return cast(str, self._access_readme_api(url, "GET", "")["_id"])

    def _render_target(self, alias: str) -> str:
        return cast(str, self._renderer.render("{{> target}}", self._targets_info[alias]))

    def _render_options_body(self, scope_help_info: Dict) -> str:
        """Renders the body of a single options help page."""
        return cast(str, self._renderer.render("{{> scoped_options}}", scope_help_info))

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

        There are three top-level pages under that category:
        - Global options
        - The Goals parent page
        - The Subsystems parent page

        The individual pages for each goal/subsystem are nested under the two parent pages.
        """
        # Docs appear on the site in creation order.  If we only create new docs
        # that don't already exist then they will appear at the end, instead of in
        # alphabetical order. So we first delete all previous docs, then recreate them.
        #
        # Note that deleting a non-empty parent will fail, so we delete children first.
        def do_delete(doc_to_delete):
            for child in doc_to_delete.get("children", []):
                do_delete(child)
            self._delete(doc_to_delete["slug"])

        docs = self._access_readme_api("categories/reference/docs", "GET", "")

        for doc in docs:
            do_delete(doc)

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
        all_goals_doc_id = self._get_id("docs/reference-all-goals")
        for scope, shi in sorted(goals.items()):
            self._create(
                parent_doc_id=all_goals_doc_id,
                slug_suffix=scope,
                title=scope,
                body=self._render_options_body(shi),
            )

        all_subsystems_doc_id = self._get_id("docs/reference-all-subsystems")
        for scope, shi in sorted(subsystems.items()):
            self._create(
                parent_doc_id=all_subsystems_doc_id,
                slug_suffix=scope,
                title=scope,
                body=self._render_options_body(shi),
            )

        all_targets_doc_id = self._get_id("docs/reference-all-targets")
        for alias, data in sorted(self._targets_info.items()):
            self._create(
                parent_doc_id=all_targets_doc_id,
                slug_suffix=alias,
                title=alias,
                body=self._render_target(alias),
            )


if __name__ == "__main__":
    main()
