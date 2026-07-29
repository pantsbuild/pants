# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler

import pytest

from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DownloadFile,
    FileContent,
    FileDigest,
    Snapshot,
)
from pants.engine.internals.buildbarn_integration_tests.stack import (
    CACHE_SPECULATION_DELAY_MILLIS,
    CacheOnlyBuildbarn,
    LocalBuildbarnStack,
    should_skip_for_missing_docker,
)
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import http_server
from pants.util.logging import LogLevel

pytestmark = pytest.mark.skipif(
    should_skip_for_missing_docker(), reason="Docker is required for Buildbarn tests"
)


# The file being downloaded, standing in for an external tool release (shellcheck, a
# python-build-standalone interpreter, ...). Downloads always declare the expected digest of the
# file up front (in `known_versions`, `http_source`, etc.), so every path below — origin download
# and cache hit alike — verifies the received bytes against this digest.
FILE_CONTENT = b"#!/bin/sh\necho this stands in for a real external tool release\n"
FILE_DIGEST = FileDigest(hashlib.sha256(FILE_CONTENT).hexdigest(), len(FILE_CONTENT))


@dataclass
class Origin:
    """The state of the origin server (standing in for e.g. github.com)."""

    request_count: int = 0
    healthy: bool = True


def origin_handler(origin: Origin) -> type[BaseHTTPRequestHandler]:
    """An origin HTTP server which counts every request, and which can be taken down (it then
    returns 504 for everything, like GitHub during an outage)."""

    class OriginHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            origin.request_count += 1
            if origin.healthy:
                self.send_response(200)
                self.send_header("Content-Length", f"{len(FILE_CONTENT)}")
                self.end_headers()
                self.wfile.write(FILE_CONTENT)
            else:
                self.send_response(504)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def log_message(self, format, *args):
            # Keep request logging out of the test output.
            pass

    return OriginHandler


def fresh_machine(
    buildbarn: CacheOnlyBuildbarn,
    *,
    remote_cache_downloads: bool = True,
    instance_name: str | None = None,
) -> RuleRunner:
    """A machine with completely empty local caches (like a fresh, ephemeral CI runner),
    configured to read and write the Buildbarn remote cache."""
    return RuleRunner(
        rules=[
            QueryRule(Snapshot, [DownloadFile]),
            QueryRule(DigestContents, [Digest]),
            QueryRule(Digest, [CreateDigest]),
            QueryRule(ProcessResult, [Process]),
        ],
        isolated_local_store=True,
        bootstrap_args=[
            "--remote-cache-read",
            "--remote-cache-write",
            f"--remote-store-address={buildbarn.address}",
            f"--remote-instance-name={instance_name or buildbarn.instance_name}",
            "--remote-cache-downloads" if remote_cache_downloads else "--no-remote-cache-downloads",
        ],
    )


def test_downloads_survive_an_origin_outage_via_the_remote_cache() -> None:
    """The end-to-end regression test for the issue motivating `[GLOBAL].remote_cache_downloads`
    (https://github.com/pantsbuild/pants/issues/16785): CI builds failed whenever GitHub returned
    5xx errors while a machine downloaded an external tool, because downloads never used the
    remote cache — a fresh machine had no caching layer between it and the origin, no matter how
    many caches were configured.

    The story, against a real Buildbarn remote cache:

    1. While the origin is healthy, machine A downloads the file, verifies its digest, and
       records it in the remote cache.
    2. The origin goes down.
    3. Machine B — brand new, empty local caches — still succeeds, without sending a single
       request to the dead origin: the download is served from the remote cache and re-verified
       against the expected digest.
    4. Machine C — also brand new, but with download caching disabled, which is exactly how
       every prior version of Pants behaved — fails with the origin's 504 despite the remote
       cache holding everything it needs.
    """
    origin = Origin()
    with LocalBuildbarnStack() as buildbarn, http_server(origin_handler(origin)) as port:
        download = DownloadFile(f"http://127.0.0.1:{port}/tool-v1.2.3.tar.gz", FILE_DIGEST)

        # 1. Machine A downloads from the healthy origin. The remote cache has never seen this
        # URL, so the fetch really does hit the origin...
        machine_a = fresh_machine(buildbarn, remote_cache_downloads=True)
        snapshot_a = machine_a.request(Snapshot, [download])
        assert snapshot_a.files == ("tool-v1.2.3.tar.gz",)
        assert origin.request_count == 1
        assert machine_a.scheduler.get_metrics()["remote_download_cache_requests_uncached"] == 1
        # ...and the verified file is then uploaded to the remote cache in the background.
        time.sleep(1)

        # 2. The origin goes down: every request to it now returns 504.
        origin.healthy = False

        # 3. Machine B, with empty local caches, downloads the same URL: it succeeds with the
        # exact bytes machine A verified, and the dead origin is never contacted.
        machine_b = fresh_machine(buildbarn, remote_cache_downloads=True)
        snapshot_b = machine_b.request(Snapshot, [download])
        assert snapshot_b == snapshot_a
        contents = machine_b.request(DigestContents, [snapshot_b.digest])
        assert [(f.path, f.content) for f in contents] == [("tool-v1.2.3.tar.gz", FILE_CONTENT)]
        assert origin.request_count == 1
        assert machine_b.scheduler.get_metrics()["remote_download_cache_requests_cached"] == 1

        # 4. Machine C behaves like Pants did before download caching existed: it never consults
        # the remote cache, so the same download retries against the dead origin and then fails
        # the build with the origin's error — the exact failure mode from pants#16785.
        machine_c = fresh_machine(buildbarn, remote_cache_downloads=False)
        with pytest.raises(ExecutionError) as exc:
            machine_c.request(Snapshot, [download])
        assert "Server error (504)" in str(exc.value)
        assert origin.request_count > 1
        assert "remote_download_cache_requests" not in machine_c.scheduler.get_metrics()


def test_bytes_already_in_the_cas_never_satisfy_a_download() -> None:
    """The remote cache only serves a download when some machine previously verified that the
    URL itself serves those bytes: file content that is merely present in the CAS (here:
    uploaded as the output of a remotely-cached process) is never trusted for a URL.

    This strictness is deliberate. If content-addressed bytes from anywhere could satisfy a
    download, a mistyped or dead URL paired with a stale-but-correct digest would silently keep
    "working" until the cache evicted the file, and then break some unrelated build much later
    (https://github.com/pantsbuild/pants/issues/13255). Instead, each URL is fetched and
    digest-verified for real once, and only that verified association is served from the cache.
    """
    origin = Origin()
    with LocalBuildbarnStack() as buildbarn, http_server(origin_handler(origin)) as port:
        download = DownloadFile(f"http://127.0.0.1:{port}/tool-v1.2.3.tar.gz", FILE_DIGEST)

        # A process (not a download) produces a file with the exact bytes the download expects,
        # and its output is uploaded to the remote cache.
        # NB: Built per machine, so that each machine materializes the process's input into its
        # own local store; the process itself (and so its cache key) is identical on every
        # machine.
        def produce_tool_process(machine: RuleRunner) -> Process:
            input_digest = machine.request(
                Digest, [CreateDigest([FileContent("input.bin", FILE_CONTENT)])]
            )
            return Process(
                ["/bin/cp", "input.bin", "tool-v1.2.3.tar.gz"],
                description="Produce a file with the same bytes as the download",
                input_digest=input_digest,
                output_files=["tool-v1.2.3.tar.gz"],
                level=LogLevel.INFO,
                remote_cache_speculation_delay_millis=CACHE_SPECULATION_DELAY_MILLIS,
            )

        machine_a = fresh_machine(buildbarn)
        machine_a.request(ProcessResult, [produce_tool_process(machine_a)])
        time.sleep(1)  # Let the background upload to the remote cache land.

        # Premise check: those bytes really are in the remote cache and servable — a fresh
        # machine re-running the process is handed the identical file without executing it.
        machine_b = fresh_machine(buildbarn)
        result_b = machine_b.request(ProcessResult, [produce_tool_process(machine_b)])
        contents = machine_b.request(DigestContents, [result_b.output_digest])
        assert [(f.path, f.content) for f in contents] == [("tool-v1.2.3.tar.gz", FILE_CONTENT)]
        assert machine_b.scheduler.get_metrics()["remote_cache_requests_cached"] == 1

        # And yet downloading a URL that expects that digest still fetches from the origin:
        # no machine has ever verified that THIS URL serves those bytes.
        machine_c = fresh_machine(buildbarn)
        snapshot = machine_c.request(Snapshot, [download])
        assert snapshot.files == ("tool-v1.2.3.tar.gz",)
        assert origin.request_count == 1
        assert machine_c.scheduler.get_metrics()["remote_download_cache_requests_uncached"] == 1


def test_evicted_file_content_falls_back_to_the_origin_and_reheals() -> None:
    """Remote caches evict: the recorded URL association can outlive the file content it points
    to, or the cache can lose data entirely. A machine must then fall back to downloading from
    the origin — the build still succeeds — and its fallback re-seeds the cache, so machines
    after it are protected again.
    """
    origin = Origin()
    stack = LocalBuildbarnStack()
    with stack as buildbarn, http_server(origin_handler(origin)) as port:
        download = DownloadFile(f"http://127.0.0.1:{port}/tool-v1.2.3.tar.gz", FILE_DIGEST)

        # Machine A seeds the remote cache from the healthy origin.
        machine_a = fresh_machine(buildbarn)
        machine_a.request(Snapshot, [download])
        assert origin.request_count == 1
        time.sleep(1)  # Let the background upload to the remote cache land.

        # The cache server loses the downloaded file content: stop it, wipe only its CAS
        # storage (keeping the ActionCache storage, where URL associations are recorded), and
        # start it again.
        stack.stop_cache_service()
        cas_storage = buildbarn.temp_dir / "storage-cas"
        shutil.rmtree(cas_storage)
        (cas_storage / "persistent_state").mkdir(parents=True)
        # NB: The restarted service gets a fresh host port, so `buildbarn` must be rebound.
        buildbarn = stack.start_cache_service()

        # A cold machine can no longer be served from the cache, so it falls back to the
        # origin, and re-uploads the verified file.
        machine_b = fresh_machine(buildbarn)
        machine_b.request(Snapshot, [download])
        assert origin.request_count == 2
        assert machine_b.scheduler.get_metrics()["remote_download_cache_requests_uncached"] == 1
        time.sleep(1)  # Let the re-upload land.

        # That fallback healed the cache: the next cold machine is served from it again, even
        # through an origin outage.
        origin.healthy = False
        machine_c = fresh_machine(buildbarn)
        machine_c.request(Snapshot, [download])
        assert origin.request_count == 2
        assert machine_c.scheduler.get_metrics()["remote_download_cache_requests_cached"] == 1


def test_rejected_cache_writes_degrade_gracefully() -> None:
    """Some cache servers refuse ActionCache writes from clients — this stack's Buildbarn only
    authorizes them for its configured instance name. Downloads must still work: the machine
    fetches from the origin and only the background cache write fails (visible in the metrics).
    Nothing gets recorded, though, so every fresh machine keeps going to the origin.
    """
    origin = Origin()
    with LocalBuildbarnStack() as buildbarn, http_server(origin_handler(origin)) as port:
        download = DownloadFile(f"http://127.0.0.1:{port}/tool-v1.2.3.tar.gz", FILE_DIGEST)

        # This machine uses an instance name Buildbarn's ActionCache does not allow writes for.
        machine_a = fresh_machine(buildbarn, instance_name="unauthorized-instance")
        snapshot = machine_a.request(Snapshot, [download])
        assert snapshot.files == ("tool-v1.2.3.tar.gz",)
        assert origin.request_count == 1
        time.sleep(1)  # Give the background cache write time to fail.
        metrics = machine_a.scheduler.get_metrics()
        assert metrics["remote_download_cache_write_attempts"] == 1
        assert metrics["remote_download_cache_write_errors"] == 1
        assert "remote_download_cache_write_successes" not in metrics

        # Nothing was recorded, so the next fresh machine downloads from the origin again.
        machine_b = fresh_machine(buildbarn, instance_name="unauthorized-instance")
        machine_b.request(Snapshot, [download])
        assert origin.request_count == 2
        assert machine_b.scheduler.get_metrics()["remote_download_cache_requests_uncached"] == 1
