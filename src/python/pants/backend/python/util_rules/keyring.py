# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import posixpath
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from pants.backend.python.subsystems.repos import PythonRepos
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent
from pants.engine.intrinsics import create_digest, execute_process
from pants.engine.process import FallibleProcessResult, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, concurrently, implicitly, rule

_FORGERY_DIR = ".keyring"


@dataclass(frozen=True)
class ForgedKeyring:
    digest: Digest
    bin_path: str | None


def _separate_authority_component(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if not (parsed.hostname and parsed.username):
        return None

    # Create a new ParseResult without the username
    cleaned_netloc = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname

    # Reconstruct the URL without userinfo
    cleaned_url = urlunparse(
        (parsed.scheme, cleaned_netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )
    return cleaned_url, parsed.username


def _make_forgery_string(repo: str, username: str, password: str) -> str:
    return f"{repo} {username} {password}"


FORGERY_SCRIPT_FORMAT_STR = """\
#!/bin/sh

# Define the hardcoded pairs and associated values
# Format: "url username password"
PAIRS="
{pairs}
"

# Loop through the pairs
echo "$PAIRS" | while read URL USERNAME PASSWORD; do
  if ["$1" = 'get' ] && [ "$2" = "$URL" ] && [ "$3" = "$USERNAME" ]; then
    echo "$PASSWORD"
    exit 0
  fi
done
exit 1
"""


@rule
async def forge_keyring(python_repos: PythonRepos) -> ForgedKeyring:
    from pants.backend.python.subsystems.keyring import KeyringSubsystem
    from pants.backend.python.util_rules.pex import PexProcess, create_pex, setup_pex_process

    subsystem = await Get(KeyringSubsystem)
    if not subsystem.install_from_resolve:
        return ForgedKeyring(EMPTY_DIGEST, None)

    keyring_pex = await create_pex(subsystem.to_pex_request())

    repo_username_tuples = [
        repo_parts
        for repo in python_repos.indexes
        if (repo_parts := _separate_authority_component(repo))
    ]
    forgery_processes = await concurrently(
        setup_pex_process(
            PexProcess(
                keyring_pex,
                description=f"Forging keyring for {repo_url}",
                argv=("get", repo_url, username),
                cache_scope=ProcessCacheScope.PER_SESSION,
            ),
            **implicitly(),
        )
        for repo_url, username in repo_username_tuples
    )
    forgery_process_results = await concurrently(
        execute_process(**implicitly(forgery_process)) for forgery_process in forgery_processes
    )
    forged_script = FORGERY_SCRIPT_FORMAT_STR.format(
        pairs="\n".join(
            _make_forgery_string(repo, username, result.stdout.decode())
            for (repo, username), result in zip(repo_username_tuples, forgery_process_results)
            if result.exit_code == 0
        )
    )
    forged_script_digest = await create_digest(
        CreateDigest(
            [
                FileContent(
                    posixpath.join(_FORGERY_DIR, "keyring"),
                    forged_script.encode(),
                    is_executable=True,
                )
            ]
        )
    )
    return ForgedKeyring(forged_script_digest, _FORGERY_DIR)


def rules():
    return collect_rules()
