# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
import shlex
import sys
import textwrap
from typing import Mapping

from pants.base.build_root import BuildRoot
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.specs import Specs
from pants.bsp.context import BSPContext
from pants.bsp.protocol import BSPConnection
from pants.bsp.util_rules.lifecycle import BSP_VERSION, BSPLanguageSupport
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.session import SessionValues
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.init.engine_initializer import GraphSession
from pants.option.option_types import BoolOption, FileListOption, StrListOption
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.util.docutil import bin_name
from pants.version import VERSION

_logger = logging.getLogger(__name__)


class BSPGoal(BuiltinGoal):
    name = "experimental-bsp"
    help = "Setup repository for Build Server Protocol (https://build-server-protocol.github.io/)."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return False

    server = BoolOption(
        "--server",
        default=False,
        advanced=True,
        help=(
            "Run the Build Server Protocol server. Pants will receive BSP RPC requests via the console. "
            "This should only ever be invoked via the IDE."
        ),
    )
    runner_env_vars = StrListOption(
        "--runner-env-vars",
        default=["PATH"],
        help=(
            "Environment variables to set in the BSP runner script when setting up BSP in a repository. "
            "Entries are either strings in the form `ENV_VAR=value` to set an explicit value; "
            f"or just `ENV_VAR` to copy the value from Pants' own environment when the {name} goal was run.\n\n"
            "This option only takes effect when the BSP runner script is written. If the option changes, you "
            f"must run `{bin_name()} {name}` again to write a new copy of the BSP runner script.\n\n"
            "Note: The environment variables passed to the Pants BSP server will be those set for your IDE "
            "and not your shell. For example, on macOS, the IDE is generally launched by `launchd` after "
            "clicking on a Dock icon, and not from the shell. Thus, any environment variables set for your "
            "shell will likely not be seen by the Pants BSP server. At the very least, on macOS consider "
            "writing an explicit PATH into the BSP runner script via this option."
        ),
        advanced=True,
    )

    groups_config_files = FileListOption(
        "--groups-config-files",
        help=(
            "A list of config files that define groups of Pants targets to expose to IDEs via Build Server Protocol.\n\n"
            "Pants generally uses fine-grained targets to define the components of a build (in many cases on a file-by-file "
            "basis). Many IDEs, however, favor coarse-grained targets that contain large numbers of source files. "
            "To accommodate this distinction, the Pants BSP server will compute a set of BSP build targets to use "
            "from the groups specified in the config files set for this option. Each group will become one or more "
            "BSP build targets.\n\n"
            "Each config file is a TOML file with a `groups` dictionary with the following format for an entry:\n\n"
            "    # The dictionary key is used to identify the group. It must be unique.\n"
            "    [groups.ID1]:\n"
            "    # One or more Pants address specs defining what targets to include in the group.\n"
            "    addresses = [\n"
            '      "src/jvm::",\n'
            '      "tests/jvm::",\n'
            "    ]\n"
            "    # Filter targets to a specific resolve. Targets in a group must be from a single resolve.\n"
            "    # Format of filter is `TYPE:RESOLVE_NAME`. The only supported TYPE is `jvm`. RESOLVE_NAME must be\n"
            "    # a valid resolve name.\n"
            '    resolve = "jvm:jvm-default"\n'
            '    display_name = "Display Name"  # (Optional) Name shown to the user in the IDE.\n'
            '    base_directory = "path/from/build/root"  # (Optional) Hint to the IDE for where the build target should "live."\n'
            "\n"
            "Pants will merge the contents of the config files together. If the same ID is used for a group definition, "
            "in multiple config files, the definition in the latter config file will take effect."
        ),
    )

    def run(
        self,
        *,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        goal_options = options.for_scope(self.name)
        if goal_options.server:
            return self._run_server(
                graph_session=graph_session,
                union_membership=union_membership,
            )
        current_session_values = graph_session.scheduler_session.py_session.session_values
        env = current_session_values[CompleteEnvironment]
        return self._setup_bsp_connection(
            union_membership=union_membership, env=env, options=goal_options
        )

    def _setup_bsp_connection(
        self,
        union_membership: UnionMembership,
        env: Mapping[str, str],
        options: OptionValueContainer,
    ) -> ExitCode:
        """Setup the BSP connection file."""

        build_root = BuildRoot()
        bsp_conn_path = build_root.pathlib_path / ".bsp" / "pants.json"
        if bsp_conn_path.exists():
            print(
                f"ERROR: A BSP connection file already exists at path `{bsp_conn_path}`. "
                "Please delete that file if you intend to re-setup BSP in this repository.",
                file=sys.stderr,
            )
            return PANTS_FAILED_EXIT_CODE

        bsp_dir = build_root.pathlib_path / ".pants.d" / "bsp"

        bsp_scripts_dir = bsp_dir / "scripts"
        bsp_scripts_dir.mkdir(exist_ok=True, parents=True)

        bsp_logs_dir = bsp_dir / "logs"
        bsp_logs_dir.mkdir(exist_ok=True, parents=True)

        # Determine which environment variables to set in the BSP runner script.
        # TODO: Consider whether some of this logic could be shared with
        #  `pants.engine.environment.CompleteEnvironment.get_subset`.
        run_script_env_lines: list[str] = []
        for env_var in options.runner_env_vars:
            if "=" in env_var:
                run_script_env_lines.append(env_var)
            else:
                if env_var not in env:
                    print(
                        f"ERROR: The `[{self.name}].runner_env_vars` option is configured to add the `{env_var}` "
                        "environment variable to the BSP runner script using its value in the current environment. "
                        "That environment variable, however, is not present in the current environment. "
                        "Please either set it in the current environment first or else configure a specific value "
                        "in `pants.toml`.",
                        file=sys.stderr,
                    )
                    return PANTS_FAILED_EXIT_CODE
                run_script_env_lines.append(f"{env_var}={env[env_var]}")

        run_script_env_lines_str = "\n".join(
            [f"export {shlex.quote(line)}" for line in run_script_env_lines]
        )

        run_script_path = bsp_scripts_dir / "run-bsp.sh"
        run_script_path.write_text(
            textwrap.dedent(
                f"""\
            #!/bin/sh
            {run_script_env_lines_str}
            exec 2>>{shlex.quote(str(bsp_logs_dir / 'stderr.log'))}
            env 1>&2
            exec {shlex.quote(bin_name())} --no-pantsd {self.name} --server
            """
            )
        )
        run_script_path.chmod(0o755)
        _logger.info(f"Wrote BSP runner script to `{run_script_path}`.")

        bsp_conn_data = {
            "name": "Pants",
            "version": VERSION,
            "bspVersion": BSP_VERSION,
            "languages": sorted(
                [lang.language_id for lang in union_membership.get(BSPLanguageSupport)]
            ),
            "argv": ["./.pants.d/bsp/scripts/run-bsp.sh"],
        }

        bsp_conn_path.parent.mkdir(exist_ok=True, parents=True)
        bsp_conn_path.write_text(json.dumps(bsp_conn_data))
        _logger.info(f"Wrote BSP connection file to `{bsp_conn_path}`.")

        return PANTS_SUCCEEDED_EXIT_CODE

    def _run_server(
        self,
        *,
        graph_session: GraphSession,
        union_membership: UnionMembership,
    ) -> ExitCode:
        """Run the BSP server."""

        current_session_values = graph_session.scheduler_session.py_session.session_values
        context = BSPContext()
        session_values = SessionValues(
            {
                **current_session_values,
                BSPContext: context,
            }
        )
        scheduler_session = graph_session.scheduler_session.scheduler.new_session(
            build_id="bsp", dynamic_ui=False, session_values=session_values
        )

        saved_stdout = sys.stdout
        saved_stdin = sys.stdin
        try:
            sys.stdout = os.fdopen(sys.stdout.fileno(), "wb", buffering=0)  # type: ignore[assignment]
            sys.stdin = os.fdopen(sys.stdin.fileno(), "rb", buffering=0)  # type: ignore[assignment]
            conn = BSPConnection(
                scheduler_session,
                union_membership,
                context,
                sys.stdin,  # type: ignore[arg-type]
                sys.stdout,  # type: ignore[arg-type]
            )
            conn.run()
        finally:
            sys.stdout = saved_stdout
            sys.stdin = saved_stdin

        return ExitCode(0)
