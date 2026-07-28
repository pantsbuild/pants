// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

//! A remote tier for the two local download caches: downloaded file bytes are stored in the
//! remote CAS, and the verified URL→digest association (the remote analog of the local
//! ObservedUrls cache) is recorded as a synthetic, never-executed REAPI action in the remote
//! ActionCache (the "AC marker").
//!
//! The marker is the sole remote authority for skipping the URL fetch: if the marker misses but
//! the digest happens to already be in the CAS, we still perform the real download. This keeps
//! the ObservedUrls verification invariant airtight fleet-wide: verification is only ever skipped
//! for (URL, digest) pairs some machine genuinely fetched and digest-verified.

use std::collections::HashSet;
use std::sync::Arc;

use futures::FutureExt;
use grpc_util::prost::MessageExt;
use hashing::Digest;
use protos::pb::build::bazel::remote::execution::v2 as remexec;
use protos::pb::pants::cache::{CacheKey, CacheKeyType, ObservedUrl};
use protos::require_digest;
use remote::remote_cache::{CacheErrorThrottle, CacheErrorType, RemoteCacheWarningsBehavior};
use remote_provider::ActionCacheProvider;
use store::{Store, StoreError};
use task_executor::{Executor, TailTasks};
use url::Url;
use workunit_store::{Level, Metric, in_workunit};

/// Discriminates the synthetic download actions from real process executions, and doubles as a
/// format-version salt: bump the version to evolve the encoding without serving stale markers.
const MARKER_ARGUMENTS: [&str; 2] = ["__pants_url_download__", "v1"];

/// The path the downloaded file is exposed under in the synthetic ActionResult. Readers use the
/// marker only as an existence proof, so the path is never materialized.
const MARKER_OUTPUT_PATH: &str = "file";

/// Downloads carrying URL userinfo (`https://user:token@host/...`) may embed secrets, and
/// `file:` URLs name machine-local paths that other machines cannot fetch or verify: both are
/// excluded from remote read and write entirely. `RemoteDownloadCache`'s methods enforce this
/// themselves; callers may additionally pre-filter with this function as an optimization.
///
/// NB: Query strings are included even though presigned URLs churn markers: they are part of the
/// local ObservedUrls cache key, and the local and remote keys must agree.
pub fn url_is_cacheable_remotely(url: &Url) -> bool {
    url.scheme() != "file" && url.username().is_empty() && url.password().is_none()
}

/// The local ObservedUrls cache key for a verified (URL, digest) pair: the local tier of the
/// same association `make_marker_command` (directly below) encodes remotely. Both are
/// deliberately colocated because they MUST be fed the identical inputs — the normalized
/// `url::Url::as_str()` serialization and the expected digest. If what goes into this key ever
/// changes (as #21215 changed it), bump the format-version salt in `MARKER_ARGUMENTS` so the
/// remote tier changes with it rather than silently desynchronizing.
pub(crate) fn observed_url_key(url: &Url, digest: Digest) -> CacheKey {
    let observed_url = ObservedUrl {
        url: url.as_str().to_owned(),
        observed_digest: Some(digest.into()),
    };
    CacheKey {
        key_type: CacheKeyType::Url.into(),
        digest: Some(Digest::of_bytes(&observed_url.to_bytes()).into()),
    }
}

/// A synthetic, never-executed Command deterministically encoding the (URL, digest) pair: the
/// remote tier of `observed_url_key` above, fed the same inputs. See its doc comment.
fn make_marker_command(url: &Url, digest: Digest) -> remexec::Command {
    let mut arguments: Vec<String> = MARKER_ARGUMENTS.iter().map(ToString::to_string).collect();
    arguments.extend([
        url.as_str().to_owned(),
        digest.hash.to_hex(),
        digest.size_bytes.to_string(),
    ]);
    remexec::Command {
        arguments,
        output_paths: vec![MARKER_OUTPUT_PATH.to_owned()],
        ..remexec::Command::default()
    }
}

/// The Action wrapping the marker Command. Its input root is the empty directory (whose
/// serialized `Directory` proto is the empty blob).
fn make_marker_action(command: &remexec::Command) -> remexec::Action {
    remexec::Action {
        command_digest: Some(Digest::of_bytes(&command.to_bytes()).into()),
        input_root_digest: Some(hashing::EMPTY_DIGEST.into()),
        ..remexec::Action::default()
    }
}

/// The ActionResult recording the verified association. Referencing the file as an output means
/// completeness-checking servers only return an AC hit while the blob is still present.
/// `is_executable` mirrors the download node's `snapshot_of_one_file(path, digest, true)`.
fn make_marker_action_result(digest: Digest) -> remexec::ActionResult {
    remexec::ActionResult {
        exit_code: 0,
        output_files: vec![remexec::OutputFile {
            path: MARKER_OUTPUT_PATH.to_owned(),
            digest: Some(digest.into()),
            is_executable: true,
            ..remexec::OutputFile::default()
        }],
        ..remexec::ActionResult::default()
    }
}

/// The reader never trusts the ActionResult payload: it is solely an existence proof for the
/// digest the caller already expected. A payload whose output digest differs from the expected
/// digest is a cache miss — never an error, and never materialized. (A payload that fails to
/// decode at all instead surfaces as a provider error — kept as an error because the process
/// remote cache relies on that corruption signal — which the caller logs, throttled by
/// `remote_cache_warnings`, and likewise treats as a miss: either way the download falls back
/// to the origin and nothing is materialized.)
fn marker_matches(action_result: &remexec::ActionResult, expected_digest: Digest) -> bool {
    if action_result.exit_code != 0 {
        return false;
    }
    let [output_file] = action_result.output_files.as_slice() else {
        return false;
    };
    output_file.path == MARKER_OUTPUT_PATH
        && require_digest(output_file.digest.as_ref()) == Ok(expected_digest)
}

///
/// Remote caching for `DownloadedFile` nodes, layered behind the local ObservedUrls cache.
///
/// NB: This deliberately holds the full, remote-capable `Store` even in configurations where the
/// rest of the engine sees a local-only store: like the remote cache `CommandRunner`, the
/// download node is a remote cache code path.
///
pub struct RemoteDownloadCache {
    provider: Arc<dyn ActionCacheProvider>,
    store: Store,
    cache_read: bool,
    cache_write: bool,
    error_throttle: CacheErrorThrottle,
    executor: Executor,
}

impl RemoteDownloadCache {
    pub fn new(
        provider: Arc<dyn ActionCacheProvider>,
        store: Store,
        cache_read: bool,
        cache_write: bool,
        warnings_behavior: RemoteCacheWarningsBehavior,
        executor: Executor,
    ) -> Self {
        Self {
            provider,
            store,
            cache_read,
            cache_write,
            error_throttle: CacheErrorThrottle::new(warnings_behavior),
            executor,
        }
    }

    ///
    /// Attempt to serve the download from the remote cache: on an AC marker hit, fully
    /// materialize the expected digest into the local store. Returns true if the download was
    /// served. Errors are logged and treated as misses, so the caller falls back to the origin.
    ///
    /// URLs which are not cacheable remotely (see `url_is_cacheable_remotely`) are always a
    /// miss: the check is enforced here, not (only) at call sites, because it is what keeps
    /// secret-bearing URLs out of the shared remote cache.
    ///
    pub async fn load_cached_download(&self, url: &Url, digest: Digest, build_id: &str) -> bool {
        if !self.cache_read || !url_is_cacheable_remotely(url) {
            return false;
        }
        in_workunit!(
            "remote_download_cache_read",
            Level::Debug,
            desc = Some(format!("Remote cache lookup for download: {url}")),
            |workunit| async move {
                workunit.increment_counter(Metric::RemoteDownloadCacheRequests, 1);
                // Exactly one of the three outcome counters is incremented per request, so
                // Requests == Cached + Uncached + ReadErrors, as for `RemoteCacheRequests*`.
                let counter = match self.load_cached_download_inner(url, digest, build_id).await {
                    Ok(true) => {
                        log::debug!("remote download cache hit for: {url}");
                        Metric::RemoteDownloadCacheRequestsCached
                    }
                    Ok(false) => {
                        log::debug!("remote download cache miss for: {url}");
                        Metric::RemoteDownloadCacheRequestsUncached
                    }
                    Err(err) => {
                        self.error_throttle.log(
                            CacheErrorType::ReadError,
                            &format!("remote cache for download of {url}"),
                            err,
                        );
                        Metric::RemoteDownloadCacheReadErrors
                    }
                };
                workunit.increment_counter(counter, 1);
                counter == Metric::RemoteDownloadCacheRequestsCached
            }
        )
        .await
    }

    async fn load_cached_download_inner(
        &self,
        url: &Url,
        digest: Digest,
        build_id: &str,
    ) -> Result<bool, String> {
        let command = make_marker_command(url, digest);
        let action = make_marker_action(&command);
        let action_digest = Digest::of_bytes(&action.to_bytes());

        let Some(action_result) = self
            .provider
            .get_action_result(action_digest, build_id)
            .await?
        else {
            return Ok(false);
        };
        if !marker_matches(&action_result, digest) {
            log::debug!("Ignoring malformed remote download cache entry for {url}");
            return Ok(false);
        }

        // Eagerly materialize the bytes into the local store: backtracking cannot rescue a
        // download, so a `MissingDigest` surfacing later from its snapshot would be a hard
        // failure. The content is digest-verified as it is fetched.
        match self
            .store
            .ensure_downloaded(HashSet::from([digest]), HashSet::new())
            .await
        {
            Ok(()) => Ok(true),
            // The marker outlived the file content (e.g. the blob was evicted from the remote
            // store): a miss, not an error. The caller re-downloads from the origin and, when
            // write-enabled, restores the marker/blob pairing.
            Err(StoreError::MissingDigest(_, _)) => {
                log::debug!(
                    "remote download cache entry for {url} was present, but its file content was \
                    not; falling back to the origin"
                );
                Ok(false)
            }
            Err(StoreError::Unclassified(err)) => Err(err),
        }
    }

    ///
    /// Record the verified (URL, digest) association in the remote cache: upload the file bytes
    /// and the synthetic Action/Command (and empty input root) protos, then write the AC marker.
    ///
    /// Writing the marker asserts that some machine actually fetched this URL and got these
    /// bytes: it must only be called after the local store holds the digest-verified content.
    ///
    async fn write_back(&self, url: &Url, digest: Digest) -> Result<(), String> {
        let command = make_marker_command(url, digest);
        let action = make_marker_action(&command);

        let (command_digest, action_digest) =
            remote::remote::ensure_action_stored_locally(&self.store, &command, &action).await?;
        let input_root_digest = self
            .store
            .record_directory(&remexec::Directory::default(), true)
            .await?;

        self.store
            .ensure_remote_has_recursive(vec![
                digest,
                command_digest,
                action_digest,
                input_root_digest,
            ])
            .await
            .map_err(|err| err.to_string())?;

        self.provider
            .update_action_result(action_digest, make_marker_action_result(digest))
            .await
    }

    ///
    /// Spawn `write_back` on the session's tail tasks (as remote cache writes for processes are),
    /// so downloads don't block on a multi-MiB upload. A short-lived run can exit before the
    /// upload finishes and drop the write: this self-heals on a later cold, write-enabled run.
    ///
    /// URLs which are not cacheable remotely are never written: as for reads, the check is
    /// enforced here because it is what keeps secret-bearing URLs out of the shared remote cache.
    ///
    pub fn spawn_write_back(self: &Arc<Self>, tail_tasks: TailTasks, url: Url, digest: Digest) {
        if !self.cache_write || !url_is_cacheable_remotely(&url) {
            return;
        }
        let this = self.clone();
        let task_name = format!("remote download cache write for {url}");
        let write_fut = in_workunit!("remote_download_cache_write", Level::Trace, |workunit| {
            async move {
                workunit.increment_counter(Metric::RemoteDownloadCacheWriteAttempts, 1);
                match this.write_back(&url, digest).await {
                    Ok(()) => {
                        log::debug!("remote download cache updated for: {url}");
                        workunit.increment_counter(Metric::RemoteDownloadCacheWriteSuccesses, 1);
                    }
                    Err(err) => {
                        this.error_throttle.log(
                            CacheErrorType::WriteError,
                            &format!("remote cache for download of {url}"),
                            err,
                        );
                        workunit.increment_counter(Metric::RemoteDownloadCacheWriteErrors, 1);
                    }
                }
            }
        });
        tail_tasks.spawn_on(&task_name, self.executor.handle(), write_fut.boxed());
    }
}

/// Shared fixtures for this module's tests and the `DownloadedFile` node tests: one home for
/// the `RemoteStoreOptions` literal and the store + provider + cache assembly, so a field or
/// signature change is a single edit.
#[cfg(test)]
pub(crate) mod test_util {
    use std::collections::BTreeMap;
    use std::sync::Arc;
    use std::time::Duration;

    use grpc_util::tls;
    use store::{RemoteProvider, RemoteStoreOptions, Store};
    use tempfile::TempDir;

    use super::RemoteDownloadCache;
    use remote::remote_cache::RemoteCacheWarningsBehavior;

    pub(crate) fn remote_store_options(
        provider: RemoteProvider,
        address: String,
    ) -> RemoteStoreOptions {
        RemoteStoreOptions {
            provider,
            store_address: address,
            instance_name: None,
            tls_config: tls::Config::default(),
            headers: BTreeMap::new(),
            chunk_size_bytes: 10 * 1024 * 1024,
            timeout: Duration::from_secs(5),
            retries: 0,
            concurrency_limit: 256,
            batch_api_size_limit: 4 * 1024 * 1024,
            batch_load_enabled: false,
        }
    }

    /// A fresh local store (in its own TempDir) with `options`' remote attached, plus a
    /// `RemoteDownloadCache` holding that same (full, remote-capable) store.
    pub(crate) async fn make_download_cache(
        options: RemoteStoreOptions,
        cache_read: bool,
        cache_write: bool,
    ) -> (TempDir, Store, Arc<RemoteDownloadCache>) {
        let executor = task_executor::Executor::new();
        let dir = TempDir::new().unwrap();
        let store = Store::local_only(executor.clone(), dir.path())
            .unwrap()
            .into_with_remote(options.clone())
            .await
            .unwrap();
        let provider = remote_provider::choose_action_cache_provider(options)
            .await
            .unwrap();
        let cache = Arc::new(RemoteDownloadCache::new(
            provider,
            store.clone(),
            cache_read,
            cache_write,
            RemoteCacheWarningsBehavior::FirstOnly,
            executor,
        ));
        (dir, store, cache)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::time::{Duration, Instant};

    use bytes::Bytes;
    use hashing::Digest;
    use store::{RemoteProvider, Store};
    use task_executor::TailTasks;
    use tempfile::TempDir;
    use testutil_mock::{RequestType, StubCAS};
    use url::Url;
    use workunit_store::WorkunitStore;

    use super::test_util::{make_download_cache, remote_store_options};
    use super::*;

    const TEST_URL: &str = "https://example.com/tool.tar.gz";
    const TEST_BYTES: &[u8] = b"downloaded tool bytes";

    fn test_url() -> Url {
        Url::parse(TEST_URL).unwrap()
    }

    fn test_digest() -> Digest {
        Digest::of_bytes(TEST_BYTES)
    }

    fn marker_action_digest(url: &Url, digest: Digest) -> Digest {
        Digest::of_bytes(&make_marker_action(&make_marker_command(url, digest)).to_bytes())
    }

    async fn make_cache(
        cas: &StubCAS,
        cache_read: bool,
        cache_write: bool,
    ) -> (TempDir, Store, Arc<RemoteDownloadCache>) {
        make_download_cache(
            remote_store_options(RemoteProvider::Reapi, cas.address()),
            cache_read,
            cache_write,
        )
        .await
    }

    #[test]
    fn url_eligibility() {
        for eligible in [
            "https://example.com/foo",
            "http://example.com/foo?presigned=abc",
        ] {
            assert!(url_is_cacheable_remotely(&Url::parse(eligible).unwrap()));
        }
        for ineligible in [
            "file:/tmp/foo",
            "https://user:token@example.com/foo",
            "https://user@example.com/foo",
            "https://:token@example.com/foo",
        ] {
            assert!(!url_is_cacheable_remotely(&Url::parse(ineligible).unwrap()));
        }
    }

    #[test]
    fn marker_encoding() {
        let url = test_url();
        let digest = test_digest();

        let command = make_marker_command(&url, digest);
        assert_eq!(
            command.arguments,
            vec![
                "__pants_url_download__".to_owned(),
                "v1".to_owned(),
                TEST_URL.to_owned(),
                digest.hash.to_hex(),
                TEST_BYTES.len().to_string(),
            ]
        );
        assert_eq!(command.output_paths, vec!["file".to_owned()]);

        let action = make_marker_action(&command);
        assert_eq!(
            action.command_digest,
            Some(Digest::of_bytes(&command.to_bytes()).into())
        );
        assert_eq!(action.input_root_digest, Some(hashing::EMPTY_DIGEST.into()));

        // Distinct URLs and distinct digests must key distinct actions.
        let other_url = Url::parse("https://example.com/other.tar.gz").unwrap();
        assert_ne!(
            marker_action_digest(&url, digest),
            marker_action_digest(&other_url, digest)
        );
        assert_ne!(
            marker_action_digest(&url, digest),
            marker_action_digest(&url, Digest::of_bytes(b"other content"))
        );
    }

    #[test]
    fn marker_validation() {
        let digest = test_digest();

        assert!(marker_matches(&make_marker_action_result(digest), digest));

        let wrong_digest = make_marker_action_result(Digest::of_bytes(b"other content"));
        assert!(!marker_matches(&wrong_digest, digest));

        assert!(!marker_matches(&remexec::ActionResult::default(), digest));

        let mut failed = make_marker_action_result(digest);
        failed.exit_code = 1;
        assert!(!marker_matches(&failed, digest));

        let mut wrong_path = make_marker_action_result(digest);
        wrong_path.output_files[0].path = "other".to_owned();
        assert!(!marker_matches(&wrong_path, digest));

        let mut extra_output = make_marker_action_result(digest);
        extra_output
            .output_files
            .push(extra_output.output_files[0].clone());
        assert!(!marker_matches(&extra_output, digest));

        let mut no_digest = make_marker_action_result(digest);
        no_digest.output_files[0].digest = None;
        assert!(!marker_matches(&no_digest, digest));
    }

    #[tokio::test]
    async fn write_back_then_cold_read() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let url = test_url();
        let digest = test_digest();

        // A write-enabled machine holds the digest-verified download locally, and writes back.
        let (_dir_a, store_a, cache_a) = make_cache(&cas, true, true).await;
        store_a
            .store_file_bytes(Bytes::from_static(TEST_BYTES), true)
            .await
            .unwrap();
        cache_a.write_back(&url, digest).await.unwrap();

        assert!(cas.contains(digest.hash));
        assert!(cas.contains_action_result(marker_action_digest(&url, digest).hash));

        // A cold machine is served entirely from the remote cache, with the bytes fully
        // materialized into its local store.
        let (_dir_b, store_b, cache_b) = make_cache(&cas, true, true).await;
        assert!(cache_b.load_cached_download(&url, digest, "build_id").await);
        let loaded = store_b
            .clone()
            .into_local_only()
            .load_file_bytes_with(digest, Bytes::copy_from_slice)
            .await
            .unwrap();
        assert_eq!(loaded, Bytes::from_static(TEST_BYTES));
    }

    #[tokio::test]
    async fn write_back_then_cold_read_with_file_provider() {
        // The same round trip as `write_back_then_cold_read`, against the OpenDAL
        // `experimental-file` provider: download caching with zero REAPI infrastructure.
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let remote_dir = TempDir::new().unwrap();
        let url = test_url();
        let digest = test_digest();

        let remote_options = remote_store_options(
            RemoteProvider::ExperimentalFile,
            format!("file://{}", remote_dir.path().display()),
        );
        let make_cache = async |cache_read: bool, cache_write: bool| {
            make_download_cache(remote_options.clone(), cache_read, cache_write).await
        };

        let (_dir_a, store_a, cache_a) = make_cache(true, true).await;
        store_a
            .store_file_bytes(Bytes::from_static(TEST_BYTES), true)
            .await
            .unwrap();
        cache_a.write_back(&url, digest).await.unwrap();

        let (_dir_b, store_b, cache_b) = make_cache(true, true).await;
        assert!(cache_b.load_cached_download(&url, digest, "build_id").await);
        let loaded = store_b
            .clone()
            .into_local_only()
            .load_file_bytes_with(digest, Bytes::copy_from_slice)
            .await
            .unwrap();
        assert_eq!(loaded, Bytes::from_static(TEST_BYTES));
    }

    #[tokio::test]
    async fn blob_without_marker_is_a_miss() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let digest = test_digest();
        // The digest is already in the CAS (e.g. as a process output), but no machine has
        // verified that this URL serves it: strict semantics require a real download.
        let cas = StubCAS::builder()
            .unverified_content(digest.hash, Bytes::from_static(TEST_BYTES))
            .build()
            .await;

        let (_dir, _store, cache) = make_cache(&cas, true, true).await;
        assert!(
            !cache
                .load_cached_download(&test_url(), digest, "build_id")
                .await
        );
        // The miss came from actually consulting the AC, not from skipping the read path.
        assert_eq!(cas.request_count(RequestType::ACGetActionResult), 1);
    }

    #[tokio::test]
    async fn ineligible_urls_make_no_requests() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let digest = test_digest();

        // Even with read and write enabled and the bytes locally present, `file:` and
        // userinfo-bearing URLs must never reach the remote cache — enforced by the methods
        // themselves, independent of any call-site filtering.
        let (_dir, store, cache) = make_cache(&cas, true, true).await;
        store
            .store_file_bytes(Bytes::from_static(TEST_BYTES), true)
            .await
            .unwrap();

        for ineligible in [
            "file:/tmp/tool.tar.gz",
            "https://user:token@example.com/tool.tar.gz",
        ] {
            let url = Url::parse(ineligible).unwrap();
            assert!(!cache.load_cached_download(&url, digest, "build_id").await);
            let tail_tasks = TailTasks::new();
            cache.spawn_write_back(tail_tasks.clone(), url, digest);
            tail_tasks.wait(Duration::from_secs(10)).await;
        }

        assert_eq!(cas.request_count(RequestType::ACGetActionResult), 0);
        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 0);
        assert!(!cas.contains(digest.hash));
    }

    #[tokio::test]
    async fn marker_with_evicted_blob_is_a_miss() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let url = test_url();
        let digest = test_digest();

        let (_dir_a, store_a, cache_a) = make_cache(&cas, true, true).await;
        store_a
            .store_file_bytes(Bytes::from_static(TEST_BYTES), true)
            .await
            .unwrap();
        cache_a.write_back(&url, digest).await.unwrap();
        assert!(cas.remove(digest.hash));

        let (_dir_b, _store_b, cache_b) = make_cache(&cas, true, true).await;
        assert!(!cache_b.load_cached_download(&url, digest, "build_id").await);
    }

    #[tokio::test]
    async fn malformed_marker_is_a_miss() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let url = test_url();
        let digest = test_digest();
        let action_digest = marker_action_digest(&url, digest);
        let (_dir, _store, cache) = make_cache(&cas, true, true).await;

        // A marker with no output files at all.
        cas.action_cache.insert(
            action_digest,
            0,
            hashing::EMPTY_DIGEST,
            hashing::EMPTY_DIGEST,
        );
        assert!(!cache.load_cached_download(&url, digest, "build_id").await);

        // A marker whose payload names a different digest than the expected one: it must never
        // be materialized.
        let poisoned = make_marker_action_result(Digest::of_bytes(b"attacker controlled"));
        cas.action_cache
            .action_map
            .lock()
            .insert(action_digest.hash, poisoned);
        assert!(!cache.load_cached_download(&url, digest, "build_id").await);
    }

    #[tokio::test]
    async fn ac_errors_are_misses() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::builder().ac_always_errors().build().await;
        let (_dir, _store, cache) = make_cache(&cas, true, true).await;
        assert!(
            !cache
                .load_cached_download(&test_url(), test_digest(), "build_id")
                .await
        );
    }

    #[tokio::test]
    async fn hung_cache_lookups_time_out_and_are_misses() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        // A degraded cache server which accepts the request and then hangs (e.g. a blackholed
        // host), for far longer than the client's configured RPC timeout.
        let cas = StubCAS::builder()
            .ac_read_delay(Duration::from_secs(60))
            .build()
            .await;
        let mut options = remote_store_options(RemoteProvider::Reapi, cas.address());
        options.timeout = Duration::from_millis(250);
        let (_dir, _store, cache) = make_download_cache(options, true, true).await;

        let start = Instant::now();
        assert!(
            !cache
                .load_cached_download(&test_url(), test_digest(), "build_id")
                .await
        );
        // The lookup gave up within the configured budget ((retries + 1) x the RPC timeout) and
        // became a miss — so the caller falls back to the origin — rather than waiting on the
        // server's response or failing the build.
        assert!(start.elapsed() < Duration::from_secs(10));
    }

    #[tokio::test]
    async fn read_disabled_makes_no_requests() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let (_dir, _store, cache) = make_cache(&cas, false, true).await;
        assert!(
            !cache
                .load_cached_download(&test_url(), test_digest(), "build_id")
                .await
        );
        assert_eq!(cas.request_count(RequestType::ACGetActionResult), 0);
    }

    #[tokio::test]
    async fn spawned_write_back_writes() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let url = test_url();
        let digest = test_digest();

        let (_dir, store, cache) = make_cache(&cas, true, true).await;
        store
            .store_file_bytes(Bytes::from_static(TEST_BYTES), true)
            .await
            .unwrap();
        let tail_tasks = TailTasks::new();
        cache.spawn_write_back(tail_tasks.clone(), url.clone(), digest);
        tail_tasks.wait(Duration::from_secs(10)).await;

        assert!(cas.contains(digest.hash));
        assert!(cas.contains_action_result(marker_action_digest(&url, digest).hash));
    }

    #[tokio::test]
    async fn write_disabled_makes_no_requests() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let digest = test_digest();

        let (_dir, store, cache) = make_cache(&cas, true, false).await;
        store
            .store_file_bytes(Bytes::from_static(TEST_BYTES), true)
            .await
            .unwrap();
        let tail_tasks = TailTasks::new();
        cache.spawn_write_back(tail_tasks.clone(), test_url(), digest);
        tail_tasks.wait(Duration::from_secs(10)).await;

        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 0);
        assert!(!cas.contains(digest.hash));
    }
}
