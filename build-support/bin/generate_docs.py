# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import html
import json
import logging
import os
import pkgutil
import sys
from pathlib import Path, PosixPath
from typing import Dict, Optional, cast

import pystache
import requests

logger = logging.getLogger(__name__)


class ReferenceGenerator:
    """Generates and uploads the Pants reference documentation.

    To run use:

    ./pants \
      --backend-packages="-['internal_backend.rules_for_testing', 'internal_backend.utilities']" \
      --backend-packages="+['pants.backend.python.lint.bandit', \
        'pants.backend.python.lint.pylint', 'pants.backend.codegen.protobuf.python']" \
      --no-verify-config help-all > /tmp/help_info

    to generate the data, and then:

    ./pants run build-support/bin/generate_docs.py -- \
      --input=/tmp/help_info --api-key=<API_KEY> --sync

    Where API_KEY is your readme.io API Key, found here:
      https://dash.readme.com/project/pants/v2.0/api-key

    TODO: Integrate this into the release process.
    """

    @classmethod
    def create(cls) -> "ReferenceGenerator":
        # Note that we want to be able to run this script using `./pants run`, so having it
        # invoke `./pants help-all` itself would be unnecessarily complicated.
        # So we require the input to be provided externally.
        parser = argparse.ArgumentParser(description="Generate the Pants reference markdown files.")
        default_output_dir = PosixPath(os.path.sep) / "tmp" / "pants_docs" / "help" / "option"
        parser.add_argument(
            "--input",
            default=None,
            help="Path to a file containing the output of `./pants help-all`. "
            "If unspecified, reads from stdin.",
        )
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
            default=default_output_dir,
            type=Path,
            help="Path to a directory under which we generate the markdown files. "
            "Useful for viewing the files locally when testing and debugging "
            "the renderer.",
        )
        parser.add_argument(
            "--api-key", help="The readme.io API key to use. Required for --upload."
        )
        return ReferenceGenerator(parser.parse_args())

    def __init__(self, args):
        self._args = args

        def get_tpl(name: str) -> str:
            buf = pkgutil.get_data(__name__, f"docs_templates/{name}")
            if buf is None:
                raise ValueError(f"No such template: {name}")
            return buf.decode()

        options_scope_tpl = get_tpl("options_scope_reference.md.mustache")
        single_option_tpl = get_tpl("single_option_reference.md.mustache")
        self._renderer = pystache.Renderer(
            partials={"scoped_options": options_scope_tpl, "single_option": single_option_tpl,}
        )
        self._category_id = None  # Fetched lazily.

        # Load the data.
        if self._args.input is None:
            json_bytes = sys.stdin.read()
        else:
            json_bytes = Path(self._args.input).read_bytes()
        self._help_info = self.process_input(json_bytes.encode(), self._args.sync)

    @staticmethod
    def process_input(json_str: str, sync: bool) -> Dict:
        """Process the input, to make it easier to work with in the mustache template."""

        help_info = json.loads(json_str)
        scope_to_help_info = help_info["scope_to_help_info"]

        # Process the list of consumed_scopes into a comma-separated list, and add it to the option
        # info for the goal's scope, to make it easy to render in the goal's options page.

        def link(scope: str) -> str:
            # docsite pages link to the slug, local pages to the .md source.
            return f"reference-{scope}" if sync else f"{scope}.md"

        for goal, goal_info in help_info["name_to_goal_info"].items():
            consumed_scopes = sorted(goal_info["consumed_scopes"])
            linked_consumed_scopes = [f"[{cs}]({link(cs)})" for cs in consumed_scopes if cs]
            comma_separated_consumed_scopes = ", ".join(linked_consumed_scopes)
            scope_to_help_info[goal][
                "comma_separated_consumed_scopes"
            ] = comma_separated_consumed_scopes

        # Process the option data.

        def munge_option(option_data):
            # Munge the default str so we can display it nicely when it's multiline, while
            # still displaying it inline if it's not.
            default_str = option_data["default_str"]
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

        return cast(Dict, help_info)

    @property
    def category_id(self):
        """The id of the "Reference" category on the docsite."""
        if self._category_id is None:
            self._category_id = self._get_id("categories/reference")
        return self._category_id

    def _render_body(self, scope_help_info: Dict) -> str:
        """Renders the body of a single options help page."""
        return cast(str, self._renderer.render("{{> scoped_options}}", scope_help_info))

    def _access_readme_api(self, url_suffix: str, method: str, payload: str) -> Dict:
        """Sends requests to the readme.io API."""
        url = f"https://dash.readme.io/api/v1/{url_suffix}"
        version = "v2.0"  # TODO: Don't hardcode this.

        headers = {"content-type": "application/json", "x-readme-version": version}
        response = requests.request(
            method, url, data=payload, headers=headers, auth=(self._args.api_key, "")
        )
        response.raise_for_status()
        return cast(Dict, response.json()) if response.text else {}

    def _create(self, parent_doc_id: Optional[str], slug: str, title: str, body: str) -> None:
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

    def render(self):
        """Renders the pages to local disk.

        Useful for debugging and iterating on the markdown.
        """
        output_dir = Path(self._args.output)
        os.makedirs(output_dir, exist_ok=True)

        for shi in self._help_info["scope_to_help_info"].values():
            body = self._render_body(shi)
            path = output_dir / f"{shi['scope'] or 'GLOBAL'}.md"
            with open(str(path), "w") as fp:
                fp.write(body)
            logger.info(f"Wrote {path}")

    def sync(self):
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

        # Create the top-level docs in order.
        self._create(
            parent_doc_id=None,
            slug="reference-global",
            title="Global",
            body=self._render_body(self._help_info["scope_to_help_info"][""]),
        )
        self._create(parent_doc_id=None, slug="reference-all-goals", title="Goals", body="")
        self._create(
            parent_doc_id=None, slug="reference-all-subsystems", title="Subsystems", body=""
        )

        # Create the individual goal/subsystem docs.
        all_goals_doc_id = self._get_id("docs/reference-all-goals")
        all_subsystems_doc_id = self._get_id("docs/reference-all-subsystems")
        for scope, shi in sorted(self._help_info["scope_to_help_info"].items()):
            if scope == "":
                continue  # We've already handled the global scope.
            parent_doc_id = all_goals_doc_id if shi["is_goal"] else all_subsystems_doc_id
            slug = f"reference-{scope}"
            body = self._render_body(shi)
            self._create(parent_doc_id=parent_doc_id, slug=slug, title=scope, body=body)

    def main(self):
        if self._args.sync:
            self.sync()
        else:
            self.render()


if __name__ == "__main__":
    logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)
    ReferenceGenerator.create().main()
