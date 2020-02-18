# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import multiprocessing
import queue
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Generator, Optional

import requests
from requests import RequestException
from urllib3.exceptions import MaxRetryError
from urllib3.util.retry import Retry

from pants.cache.artifact_cache import ArtifactCache, NonfatalArtifactCacheError, UnreadableArtifact
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_classmethod

logger = logging.getLogger(__name__)


class LogLevel(Enum):
    warning = "WARNING"
    info = "INFO"
    debug = "DEBUG"


@dataclass(frozen=True)
class RequestsSession:
    """Configuration for the session object used to fetch HTTP(S) artifact cache entries.

    See
    https://github.com/psf/requests/blob/d2590ee46c0641958b6d4792a206bd5171cb247d/requests/adapters.py#L113
    for documentation on the HTTPAdapter class, and check out
    https://urllib3.readthedocs.io/en/latest/advanced-usage.html#customizing-pool-behavior for
    a description of the connection pooling implementation in urllib3.

    See
    https://github.com/urllib3/urllib3/blob/f4b36ad045ccfbbfaaadd8e69f9b32c5d81cbd84/src/urllib3/util/retry.py#L29
    for the Retry class (also from urllib3) which is used here to configure request retries.
    """

    max_connection_pools: int
    max_connections_within_pool: int
    max_retries: int
    max_retries_on_connection_errors: int
    max_retries_on_read_errors: int
    backoff_factor: float
    blocking_pool: bool
    slow_download_timeout_seconds: int

    # Global flag which is set to True if our global connection pool singleton raises a MaxRetryError.
    _max_retries_exceeded = False

    @classmethod
    def has_exceeded_retries(cls) -> bool:
        return cls._max_retries_exceeded

    class Factory(Subsystem):
        options_scope = "http-artifact-cache"

        # Maintain a connection pool of max size equaling the larger of the number of available cores,
        # or the default from the requests package (which is usually 10).
        _default_pool_size = max(multiprocessing.cpu_count(), requests.adapters.DEFAULT_POOLSIZE)
        # By default, don't perform any retries.
        _default_retries = 0

        @classmethod
        def register_options(cls, register):
            super().register_options(register)
            # TODO: Pull the `choices` from the registered log levels in the `logging` module somehow!
            register(
                "--requests-logging-level",
                type=LogLevel,
                # Reduce the somewhat verbose logging of requests.
                default=LogLevel.warning,
                advanced=True,
                help="The logging level to set the requests logger to.",
            )
            register(
                "--max-connection-pools",
                type=int,
                default=cls._default_pool_size,
                help="The max number of separate hosts to maintain urllib3 pools for. "
                "Corresponds to `pool_connections` in `requests.adapters.HTTPAdapter`.",
            )
            register(
                "--max-connections-within-pool",
                type=int,
                default=cls._default_pool_size,
                help="The max number of connections to retain within a single pool. "
                "Corresponds to `pool_maxsize` in `requests.adapters.HTTPAdapter`.",
            )
            register(
                "--max-retries",
                type=int,
                default=cls._default_retries,
                help="The max number of retries to perform for failed artifact cache requests. "
                "Corresponds to `max_retries` in in `requests.adapters.HTTPAdapter`.",
            )
            # TODO: raise an exception if these secondary retry limits exceed --max-retries (which will
            # just have no effect)?
            register(
                "--max-retries-on-connection-errors",
                type=int,
                default=cls._default_retries,
                help="The maximum number of retries to perform for requests which fail to connect."
                "\n\n--max-retries takes precedence over this option, so if this number is "
                "greater than --max-retries, the additional retries are ignored.",
            )
            register(
                "--max-retries-on-read-errors",
                type=int,
                default=cls._default_retries,
                help="The maximum number of retries to perform for requests which fail after the "
                "request is sent to the server."
                "\n\n--max-retries takes precedence over this option, so if this number is "
                "greater than --max-retries, the additional retries are ignored.",
            )
            register(
                "--backoff-factor",
                type=float,
                default=0,
                help="The backoff factor to apply between retry attempts. "
                "Set to 0 to disable backoff.",
            )
            register(
                "--blocking-pool",
                type=bool,
                help="Whether a connection pool should block instead of creating a new connection "
                "when the connection pool is already at its maximum size. "
                "Corresponds to `pool_block` in `requests.adapters.HTTPAdapter`.",
            )
            # TODO: Make a custom option type for timeout lengths which validates that the value is
            # nonzero, and perhaps parameterized by time unit (seconds, ms, ns?)!
            register(
                "--slow-download-timeout-seconds",
                type=int,
                default=60,
                help="The time to wait while downloading a cache artifact before printing a warning "
                "about a slow artifact download.",
            )

        @classmethod
        def create(cls, logger) -> "RequestsSession":
            options = cls.global_instance().get_options()
            level = getattr(logging, options.requests_logging_level.value)
            logger.setLevel(level)

            return RequestsSession(
                max_connection_pools=options.max_connection_pools,
                max_connections_within_pool=options.max_connections_within_pool,
                max_retries=options.max_retries,
                max_retries_on_connection_errors=options.max_retries_on_connection_errors,
                max_retries_on_read_errors=options.max_retries_on_read_errors,
                backoff_factor=options.backoff_factor,
                blocking_pool=options.blocking_pool,
                slow_download_timeout_seconds=options.slow_download_timeout_seconds,
            )

    @memoized_classmethod
    def _instance(cls) -> "RequestsSession":
        requests_logger = logging.getLogger("requests")
        return cls.Factory.create(requests_logger)

    def should_check_for_max_retry_error(self) -> bool:
        """Helper method extracted for convenience in testing.

        If this method returns False, pants will convert a MaxRetryError into a
        NonfatalArtifactCacheError. Otherwise, it will re-raise the MaxRetryError.
        """
        return bool(self.max_retries)

    @memoized_classmethod
    def session(cls) -> requests.Session:
        instance = cls._instance()

        session = requests.Session()

        retry_config = Retry(
            total=instance.max_retries,
            connect=instance.max_retries_on_connection_errors,
            read=instance.max_retries_on_read_errors,
            redirect=0,
            backoff_factor=instance.backoff_factor,
            raise_on_redirect=True,
            raise_on_status=True,
        )

        http_connection_adapter = requests.adapters.HTTPAdapter(
            pool_connections=instance.max_connection_pools,
            pool_maxsize=instance.max_connections_within_pool,
            max_retries=retry_config,
            pool_block=instance.blocking_pool,
        )

        session.mount("http://", http_connection_adapter)
        session.mount("https://", http_connection_adapter)

        return session


class RESTfulArtifactCache(ArtifactCache):
    """An artifact cache that stores the artifacts on a RESTful service."""

    READ_SIZE_BYTES = 4 * 1024 * 1024

    def __init__(
        self, artifact_root, best_url_selector, local, read_timeout=4.0, write_timeout=4.0
    ):
        """
        :param string artifact_root: The path under which cacheable products will be read/written.
        :param BestUrlSelector best_url_selector: Url selector that supports fail-over. Each returned
          url represents prefix for some RESTful service. We must be able to PUT and GET to any path
          under this base.
        :param BaseLocalArtifactCache local: local cache instance for storing and creating artifacts
        """
        super().__init__(artifact_root)

        self.best_url_selector = best_url_selector
        self._read_timeout_secs = read_timeout
        self._write_timeout_secs = write_timeout
        self._localcache = local

    def try_insert(self, cache_key, paths):
        # Delegate creation of artifact to local cache.
        with self._localcache.insert_paths(cache_key, paths) as tarfile:
            # Upload local artifact to remote cache.
            with open(tarfile, "rb") as infile:
                if not self._request("PUT", cache_key, body=infile):
                    raise NonfatalArtifactCacheError("Failed to PUT {0}.".format(cache_key))

    def has(self, cache_key):
        if self._localcache.has(cache_key):
            return True
        return self._request("HEAD", cache_key) is not None

    def use_cached_files(self, cache_key, results_dir=None):
        if self._localcache.has(cache_key):
            return self._localcache.use_cached_files(cache_key, results_dir)

        # The queue is used as a semaphore here, containing only a single None element. A background
        # thread is kicked off which waits with the specified timeout for the single queue element, and
        # prints a warning message if the timeout is breached.
        queue = multiprocessing.Queue()
        try:
            response = self._request("GET", cache_key)
            if response is not None:
                threading.Thread(
                    target=_log_if_no_response,
                    args=(
                        RequestsSession._instance().slow_download_timeout_seconds,
                        "\nStill downloading artifacts (either they're very large or the connection to the cache is slow)",
                        queue.get,
                    ),
                ).start()
                # Delegate storage and extraction to local cache
                byte_iter = response.iter_content(self.READ_SIZE_BYTES)
                res = self._localcache.store_and_use_artifact(cache_key, byte_iter, results_dir)
                queue.put(None)
                return res
        except Exception as e:
            logger.warning("\nError while reading from remote artifact cache: {0}\n".format(e))
            queue.put(None)
            # If we exceed the retry limits, set a global flag to avoid using the cache for the rest of
            # the pants process lifetime.
            if isinstance(e, MaxRetryError):
                logger.warning(
                    "\nMaximum retries were exceeded for the current connection pool. Avoiding "
                    "the remote cache for the rest of the pants process lifetime.\n"
                )
                RequestsSession._max_retries_exceeded = True
            # TODO(peiyu): clean up partially downloaded local file if any
            return UnreadableArtifact(cache_key, e)

        return False

    def delete(self, cache_key):
        self._localcache.delete(cache_key)
        self._request("DELETE", cache_key)

    @contextmanager
    def _request_session(self, method, url) -> Generator[requests.Session, None, None]:
        try:
            logger.debug(f"Sending {method} request to {url}")
            # TODO: fix memo.py so @memoized_classmethod is correctly recognized by mypy!
            yield RequestsSession.session()  # type: ignore[call-arg]
        except RequestException as e:
            if RequestsSession._instance().should_check_for_max_retry_error():  # type: ignore[call-arg]
                # TODO: Determine if there's a more canonical way to extract a MaxRetryError from a
                # RequestException.
                base_exc = e.args[0]
                if isinstance(base_exc, MaxRetryError):
                    raise base_exc from e
            raise NonfatalArtifactCacheError(f"Failed to {method} {url}. Error: {e}") from e

    # Returns a response if we get a 200, None if we get a 404 and raises an exception otherwise.
    def _request(self, method, cache_key, body=None) -> Optional[requests.Response]:
        # If our connection pool has experienced too many retries, we no-op on every successive
        # artifact download for the rest of the pants process lifetime.
        if RequestsSession.has_exceeded_retries():
            return None

        with self.best_url_selector.select_best_url() as best_url:
            url = self._url_for_key(best_url, cache_key)
            with self._request_session(method, url) as session:
                if "PUT" == method:
                    response = session.put(
                        url, data=body, timeout=self._write_timeout_secs, allow_redirects=True
                    )
                elif "GET" == method:
                    response = session.get(
                        url, timeout=self._read_timeout_secs, stream=True, allow_redirects=True
                    )
                elif "HEAD" == method:
                    response = session.head(
                        url, timeout=self._read_timeout_secs, allow_redirects=True
                    )
                elif "DELETE" == method:
                    response = session.delete(
                        url, timeout=self._write_timeout_secs, allow_redirects=True
                    )
                else:
                    raise ValueError("Unknown request method {0}".format(method))

            # Allow all 2XX responses. E.g., nginx returns 201 on PUT. HEAD may return 204.
            if int(response.status_code / 100) == 2:
                return response
            elif response.status_code == 404:
                logger.debug("404 returned for {0} request to {1}".format(method, url))
                return None
            else:
                raise NonfatalArtifactCacheError(
                    "Failed to {0} {1}. Error: {2} {3}".format(
                        method, url, response.status_code, response.reason
                    )
                )

    def _url_suffix_for_key(self, cache_key):
        return "{0}/{1}.tgz".format(cache_key.id, cache_key.hash)

    def _url_for_key(self, url, cache_key):
        path_prefix = url.path.rstrip("/")
        path = "{0}/{1}".format(path_prefix, self._url_suffix_for_key(cache_key))
        return "{0}://{1}{2}".format(url.scheme, url.netloc, path)


def _log_if_no_response(timeout_seconds, message, getter):
    while True:
        try:
            getter(True, timeout_seconds)
            return
        except queue.Empty:
            logger.info(message)
