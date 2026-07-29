// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;
use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use cache::PersistentCache;
use deepsize::DeepSizeOf;
use fs::RelativePath;
use graph::CompoundNode;
use pyo3::prelude::Python;
use store::Store;
use task_executor::TailTasks;
use url::Url;

use super::{NodeKey, NodeResult};
use crate::context::Context;
use crate::downloads;
use crate::externs;
use crate::externs::fs::PyFileDigest;
use crate::python::{Key, throw};
use crate::remote_download_cache::{
    RemoteDownloadCache, observed_url_key, url_is_cacheable_remotely,
};

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct DownloadedFile(pub Key);

/// The state of the machine a download runs against: its local stores and caches, HTTP client,
/// and (when remote caching is configured) the remote download cache. Grouped separately from
/// the per-download arguments so that tests can assemble one without building a full `Core`.
pub(crate) struct DownloadDeps<'a> {
    pub(crate) local_cache: &'a PersistentCache,
    pub(crate) store: Store,
    pub(crate) http_client: &'a reqwest::Client,
    pub(crate) remote_download_cache: Option<&'a Arc<RemoteDownloadCache>>,
    pub(crate) tail_tasks: TailTasks,
    pub(crate) build_id: &'a str,
}

pub(crate) async fn load_or_download(
    deps: DownloadDeps<'_>,
    url: Url,
    auth_headers: BTreeMap<String, String>,
    digest: hashing::Digest,
    retry_delay_duration: Duration,
    max_attempts: NonZeroUsize,
) -> Result<store::Snapshot, String> {
    let DownloadDeps {
        local_cache,
        store,
        http_client,
        remote_download_cache,
        tail_tasks,
        build_id,
    } = deps;
    let file_name = url
        .path_segments()
        .and_then(Iterator::last)
        .map(str::to_owned)
        .ok_or_else(|| format!("Error getting the file name from the parsed URL: {url}"))?;
    let path = RelativePath::new(&file_name).map_err(|e| {
        format!(
            "The file name derived from {} was {} which is not relative: {:?}",
            url, file_name, e
        )
    })?;

    // See if we have observed this URL and Digest before: if so, see whether we already have the
    // Digest fetched. The extra layer of indirection through the PersistentCache is to sanity
    // check that a Digest has ever been observed at the given URL.
    // NB: The auth_headers are not part of the key.
    let url_key = observed_url_key(&url, digest);
    let have_observed_url = local_cache.load(&url_key).await?.is_some();

    // If we hit the ObservedUrls cache, then we have successfully fetched this Digest from
    // this URL before. If we still have the bytes, then we skip fetching the content again.
    // NB: When the node's store handle is remote-capable (remote execution, or
    // `cache_content_behavior != fetch`), this probe itself backfills locally-evicted bytes from
    // the remote CAS — pre-existing behavior, which bypasses the remote download cache's
    // metrics, warning throttling, and marker re-assert below.
    let usable_in_store =
        have_observed_url && (store.load_file_bytes_with(digest, |_| ()).await.is_ok());

    if !usable_in_store {
        let remote_download_cache =
            remote_download_cache.filter(|_| url_is_cacheable_remotely(&url));

        // The local caches cannot serve this download: consult the remote cache (when
        // configured), which serves only (URL, digest) pairs some machine genuinely fetched and
        // digest-verified.
        let served_remotely = match remote_download_cache {
            Some(cache) => cache.load_cached_download(&url, digest, build_id).await,
            None => false,
        };

        if !served_remotely {
            downloads::download(
                http_client,
                store.clone(),
                url.clone(),
                auth_headers,
                file_name,
                digest,
                retry_delay_duration,
                max_attempts,
            )
            .await?;
        }
        // The value was successfully fetched and matched the digest (from the origin, or from the
        // remote cache, where it was recorded by a machine which fetched it from the origin):
        // record in the ObservedUrls cache.
        local_cache.store(&url_key, Bytes::from("")).await?;
        if let Some(remote_download_cache) = remote_download_cache {
            // Record the verified association remotely in the background. When the download was
            // served from the remote cache this re-asserts the existing marker (deliberately
            // reusing the full write-back for simplicity), which refreshes it on servers whose
            // action-cache entries can be overwritten (e.g. REAPI); on stores with immutable
            // entries (e.g. the GitHub Actions cache) the re-assert is a no-op.
            remote_download_cache.spawn_write_back(tail_tasks, url, digest);
        }
    }
    store.snapshot_of_one_file(path, digest, true).await
}

impl DownloadedFile {
    pub(super) async fn run_node(self, context: Context) -> NodeResult<store::Snapshot> {
        let (url_str, expected_digest, auth_headers, retry_delay_duration, max_attempts) =
            Python::attach(|py| {
                let py_download_file_val = self.0.to_value();
                let py_download_file = py_download_file_val.bind(py);
                let url_str: String = externs::getattr(py_download_file, "url")
                    .map_err(|e| format!("Failed to get `url` for field: {e}"))?;
                let auth_headers =
                    externs::getattr_from_str_frozendict(py_download_file, "auth_headers");
                let py_file_digest: PyFileDigest =
                    externs::getattr(py_download_file, "expected_digest")?;
                let retry_delay_duration: Duration =
                    externs::getattr(py_download_file, "retry_error_duration")?;
                let max_attempts: NonZeroUsize =
                    externs::getattr(py_download_file, "max_attempts")?;
                Ok::<_, String>((
                    url_str,
                    py_file_digest.0,
                    auth_headers,
                    retry_delay_duration,
                    max_attempts,
                ))
            })?;

        let url = Url::parse(&url_str)
            .map_err(|err| throw(format!("Error parsing URL {url_str}: {err}")))?;
        load_or_download(
            DownloadDeps {
                local_cache: &context.core.local_cache,
                store: context.core.store(),
                http_client: &context.core.http_client,
                remote_download_cache: context.core.remote_download_cache.as_ref(),
                tail_tasks: context.session.tail_tasks(),
                build_id: context.session.build_id(),
            },
            url,
            auth_headers,
            expected_digest,
            retry_delay_duration,
            max_attempts,
        )
        .await
        .map_err(throw)
    }
}

impl CompoundNode<NodeKey> for DownloadedFile {
    type Item = store::Snapshot;
}

impl From<DownloadedFile> for NodeKey {
    fn from(n: DownloadedFile) -> Self {
        NodeKey::DownloadedFile(n)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::num::NonZeroUsize;
    use std::sync::{
        Arc,
        atomic::{AtomicU32, Ordering},
    };
    use std::time::{Duration, Instant};

    use axum::http::{HeaderMap, header::AUTHORIZATION};
    use axum::{Router, extract::State, response::IntoResponse, routing::get};
    use bytes::Bytes;
    use cache::PersistentCache;
    use hashing::Digest;
    use reqwest::StatusCode;
    use store::{RemoteProvider, RemoteStoreOptions, Store};
    use task_executor::TailTasks;
    use tempfile::TempDir;
    use testutil_mock::{RequestType, StubCAS};
    use url::Url;
    use workunit_store::WorkunitStore;

    use super::{DownloadDeps, load_or_download};
    use crate::downloads::test_server::spawn_test_server;
    use crate::remote_download_cache::test_util::{make_download_cache, remote_store_options};
    use crate::remote_download_cache::{RemoteDownloadCache, observed_url_key};

    const TEST_RESPONSE: &[u8] = b"the downloaded file bytes";

    /// An origin HTTP server which succeeds for the first `successes` requests and returns 504
    /// for every request after that, counting all requests it receives.
    fn start_origin(successes: u32) -> (Url, Arc<AtomicU32>) {
        #[derive(Clone)]
        struct HandlerState {
            requests: Arc<AtomicU32>,
            successes: u32,
        }

        let requests = Arc::new(AtomicU32::new(0));
        let router = Router::new()
            .route(
                "/file.txt",
                get(move |State(state): State<HandlerState>| async move {
                    let request = state.requests.fetch_add(1, Ordering::SeqCst);
                    if request < state.successes {
                        (StatusCode::OK, TEST_RESPONSE).into_response()
                    } else {
                        (StatusCode::GATEWAY_TIMEOUT, &b"504"[..]).into_response()
                    }
                }),
            )
            .with_state(HandlerState {
                requests: requests.clone(),
                successes,
            });

        let addr = spawn_test_server(router);
        let url = Url::parse(&format!("http://127.0.0.1:{}/file.txt", addr.port())).unwrap();
        (url, requests)
    }

    /// An origin like `start_origin`, but private: requests must carry exactly this
    /// `Authorization` header, or they are rejected with a 401. All requests are counted.
    fn start_authed_origin(required_authorization: &'static str) -> (Url, Arc<AtomicU32>) {
        #[derive(Clone)]
        struct HandlerState {
            requests: Arc<AtomicU32>,
            required_authorization: &'static str,
        }

        let requests = Arc::new(AtomicU32::new(0));
        let router = Router::new()
            .route(
                "/file.txt",
                get(
                    move |State(state): State<HandlerState>, headers: HeaderMap| async move {
                        state.requests.fetch_add(1, Ordering::SeqCst);
                        if headers
                            .get(AUTHORIZATION)
                            .and_then(|value| value.to_str().ok())
                            == Some(state.required_authorization)
                        {
                            (StatusCode::OK, TEST_RESPONSE).into_response()
                        } else {
                            (StatusCode::UNAUTHORIZED, &b"401"[..]).into_response()
                        }
                    },
                ),
            )
            .with_state(HandlerState {
                requests: requests.clone(),
                required_authorization,
            });

        let addr = spawn_test_server(router);
        let url = Url::parse(&format!("http://127.0.0.1:{}/file.txt", addr.port())).unwrap();
        (url, requests)
    }

    /// The state of a single machine: a local store and ObservedUrls cache (both cold), plus,
    /// when a StubCAS is given, a remote download cache configured the way `Core::new` does it in
    /// the default remote caching configuration: the machine's own store is the local-only view,
    /// while the remote download cache holds the full remote-capable store.
    struct Pod {
        _store_dir: TempDir,
        _cache_dir: TempDir,
        store: Store,
        local_cache: PersistentCache,
        remote_download_cache: Option<Arc<RemoteDownloadCache>>,
        http_client: reqwest::Client,
        tail_tasks: TailTasks,
    }

    impl Pod {
        async fn new(cas: Option<&StubCAS>, cache_read: bool, cache_write: bool) -> Pod {
            match cas {
                Some(cas) => {
                    Self::new_with_remote_options(
                        remote_store_options(RemoteProvider::Reapi, cas.address()),
                        cache_read,
                        cache_write,
                    )
                    .await
                }
                None => {
                    let executor = task_executor::Executor::new();
                    let (cache_dir, local_cache) = Self::make_local_cache(&executor);
                    let store_dir = TempDir::new().unwrap();
                    let store = Store::local_only(executor, store_dir.path()).unwrap();
                    Pod {
                        _store_dir: store_dir,
                        _cache_dir: cache_dir,
                        store,
                        local_cache,
                        remote_download_cache: None,
                        http_client: reqwest::Client::new(),
                        tail_tasks: TailTasks::new(),
                    }
                }
            }
        }

        /// As `new(Some(cas), ..)`, but with custom remote store options (e.g. a short RPC
        /// timeout).
        async fn new_with_remote_options(
            options: RemoteStoreOptions,
            cache_read: bool,
            cache_write: bool,
        ) -> Pod {
            let executor = task_executor::Executor::new();
            let (cache_dir, local_cache) = Self::make_local_cache(&executor);
            let (store_dir, full_store, remote_download_cache) =
                make_download_cache(options, cache_read, cache_write).await;
            Pod {
                _store_dir: store_dir,
                _cache_dir: cache_dir,
                store: full_store.into_local_only(),
                local_cache,
                remote_download_cache: Some(remote_download_cache),
                http_client: reqwest::Client::new(),
                tail_tasks: TailTasks::new(),
            }
        }

        fn make_local_cache(executor: &task_executor::Executor) -> (TempDir, PersistentCache) {
            let cache_dir = TempDir::new().unwrap();
            let local_cache = PersistentCache::new(
                cache_dir.path(),
                50 * 1024 * 1024,
                executor.clone(),
                Duration::from_secs(2 * 60 * 60),
                1,
            )
            .unwrap();
            (cache_dir, local_cache)
        }

        fn deps(&self) -> DownloadDeps<'_> {
            DownloadDeps {
                local_cache: &self.local_cache,
                store: self.store.clone(),
                http_client: &self.http_client,
                remote_download_cache: self.remote_download_cache.as_ref(),
                tail_tasks: self.tail_tasks.clone(),
                build_id: "build_id",
            }
        }

        async fn download(&self, url: &Url, digest: Digest) -> Result<store::Snapshot, String> {
            self.download_with_headers(url, digest, BTreeMap::new())
                .await
        }

        async fn download_with_headers(
            &self,
            url: &Url,
            digest: Digest,
            auth_headers: BTreeMap<String, String>,
        ) -> Result<store::Snapshot, String> {
            load_or_download(
                self.deps(),
                url.clone(),
                auth_headers,
                digest,
                Duration::from_millis(10),
                NonZeroUsize::new(1).unwrap(),
            )
            .await
        }

        // NB: `TailTasks::wait` consumes the shared inner task set, so this is single-shot: a
        // second call on the same Pod returns immediately without waiting for anything.
        async fn wait_for_write_back(&self) {
            self.tail_tasks.clone().wait(Duration::from_secs(10)).await;
        }

        async fn assert_bytes_are_local(&self, digest: Digest) {
            let loaded = self
                .store
                .clone()
                .into_local_only()
                .load_file_bytes_with(digest, Bytes::copy_from_slice)
                .await
                .unwrap();
            assert_eq!(loaded, Bytes::from_static(TEST_RESPONSE));
        }
    }

    fn test_digest() -> Digest {
        Digest::of_bytes(TEST_RESPONSE)
    }

    #[tokio::test]
    async fn cold_pod_is_served_from_remote_cache_when_origin_is_down() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        // The origin serves exactly one request, then returns 504s (a GitHub incident).
        let (url, origin_requests) = start_origin(1);
        let digest = test_digest();

        // Pod A downloads from the live origin and writes back.
        let pod_a = Pod::new(Some(&cas), true, true).await;
        pod_a.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
        pod_a.wait_for_write_back().await;
        assert!(cas.contains(digest.hash));
        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 1);

        // A cold pod B succeeds via the remote cache: the origin is never contacted.
        let pod_b = Pod::new(Some(&cas), true, true).await;
        let snapshot = pod_b.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
        assert_eq!(snapshot.files(), vec![std::path::PathBuf::from("file.txt")]);
        pod_b.assert_bytes_are_local(digest).await;

        // Serving from the remote cache re-asserted the marker (the flow-2 re-assert).
        pod_b.wait_for_write_back().await;
        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 2);

        // A second download on pod B is served by its local caches: no new AC or origin requests.
        let ac_gets = cas.request_count(RequestType::ACGetActionResult);
        pod_b.download(&url, digest).await.unwrap();
        assert_eq!(cas.request_count(RequestType::ACGetActionResult), ac_gets);
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn cas_blob_without_marker_still_downloads_from_origin() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let digest = test_digest();
        // The digest is already in the CAS (e.g. as a process output), but no marker exists:
        // strict semantics require the real download, which then mints the marker.
        let cas = StubCAS::builder()
            .unverified_content(digest.hash, Bytes::from_static(TEST_RESPONSE))
            .build()
            .await;
        let (url, origin_requests) = start_origin(1);

        let pod = Pod::new(Some(&cas), true, true).await;
        pod.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
        // The AC was consulted and correctly missed: the origin download above happened despite
        // the blob being present in the CAS, not because the read path was skipped.
        assert_eq!(cas.request_count(RequestType::ACGetActionResult), 1);

        pod.wait_for_write_back().await;
        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 1);
    }

    #[tokio::test]
    async fn evicted_blob_falls_back_to_origin_and_reuploads() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        let (url, origin_requests) = start_origin(2);
        let digest = test_digest();

        let pod_a = Pod::new(Some(&cas), true, true).await;
        pod_a.download(&url, digest).await.unwrap();
        pod_a.wait_for_write_back().await;

        // The blob is evicted from the remote store, but the marker survives.
        assert!(cas.remove(digest.hash));

        // A cold pod falls back to the origin, then restores the marker/blob pairing: the blob
        // is re-uploaded AND the marker is re-written, not merely one of the two.
        let pod_b = Pod::new(Some(&cas), true, true).await;
        pod_b.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 2);
        pod_b.wait_for_write_back().await;
        assert!(cas.contains(digest.hash));
        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 2);
    }

    #[tokio::test]
    async fn hung_cache_delays_but_does_not_break_downloads() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        // A degraded cache server which hangs on every lookup (e.g. a blackholed host), for far
        // longer than the client's configured RPC timeout. The origin is healthy.
        let cas = StubCAS::builder()
            .ac_read_delay(Duration::from_secs(60))
            .build()
            .await;
        let (url, origin_requests) = start_origin(1);
        let digest = test_digest();

        let mut options = remote_store_options(RemoteProvider::Reapi, cas.address());
        options.timeout = Duration::from_millis(250);
        let pod = Pod::new_with_remote_options(options, true, true).await;

        // The download waits out the cache lookup's timeout budget, then falls back to the
        // origin and succeeds: a degraded cache costs latency, never the build.
        let start = Instant::now();
        pod.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
        assert!(start.elapsed() < Duration::from_secs(10));
    }

    #[tokio::test]
    async fn auth_headers_reach_the_origin_and_are_excluded_from_the_cache_key() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        // A private origin, e.g. one addressed via the S3 URLDownloadHandler (which signs
        // requests via auth_headers): it rejects requests without the right credentials.
        let (url, origin_requests) = start_authed_origin("Bearer org-token");
        let digest = test_digest();

        // Pod A's download succeeds only because its auth header genuinely reached the origin
        // (the origin 401s otherwise), and the verified file is then written back to the shared
        // remote cache: auth-header downloads participate in remote caching.
        let pod_a = Pod::new(Some(&cas), true, true).await;
        let auth_headers =
            BTreeMap::from([("Authorization".to_owned(), "Bearer org-token".to_owned())]);
        pod_a
            .download_with_headers(&url, digest, auth_headers)
            .await
            .unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
        pod_a.wait_for_write_back().await;
        assert!(cas.contains(digest.hash));

        // Auth headers are deliberately not part of the download cache key (local or remote): a
        // cold pod with no credentials at all is served the private origin's bytes from the
        // cache, without the origin ever being contacted. (This is the documented trust
        // implication of including auth-header downloads: the shared cache is the trust domain.)
        let pod_b = Pod::new(Some(&cas), true, true).await;
        pod_b.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
        pod_b.assert_bytes_are_local(digest).await;
    }

    #[tokio::test]
    async fn file_urls_never_touch_the_remote_cache() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;

        let tempdir = TempDir::new().unwrap();
        let file_path = tempdir.path().join("file.txt");
        std::fs::write(&file_path, TEST_RESPONSE).unwrap();
        let url = Url::parse(&format!("file:{}", file_path.display())).unwrap();
        let digest = test_digest();

        let pod = Pod::new(Some(&cas), true, true).await;
        pod.download(&url, digest).await.unwrap();
        pod.wait_for_write_back().await;

        assert_eq!(cas.request_count(RequestType::ACGetActionResult), 0);
        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 0);
        assert!(!cas.contains(digest.hash));
    }

    #[tokio::test]
    async fn local_marker_hit_makes_no_remote_requests() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let cas = StubCAS::empty().await;
        // The origin is hard down.
        let (url, origin_requests) = start_origin(0);
        let digest = test_digest();

        // The pod has both the bytes and the ObservedUrls marker: the warm path.
        let pod = Pod::new(Some(&cas), true, true).await;
        pod.store
            .store_file_bytes(Bytes::from_static(TEST_RESPONSE), true)
            .await
            .unwrap();
        pod.local_cache
            .store(&observed_url_key(&url, digest), Bytes::from(""))
            .await
            .unwrap();

        pod.download(&url, digest).await.unwrap();
        pod.wait_for_write_back().await;
        assert_eq!(origin_requests.load(Ordering::SeqCst), 0);
        assert_eq!(cas.request_count(RequestType::ACGetActionResult), 0);
        assert_eq!(cas.request_count(RequestType::ACUpdateActionResult), 0);
    }

    #[tokio::test]
    async fn remote_caching_disabled_downloads_from_origin() {
        let (_workunit_store, _workunit) = WorkunitStore::setup_for_tests();
        let (url, origin_requests) = start_origin(1);
        let digest = test_digest();

        let pod = Pod::new(None, false, false).await;
        pod.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);

        // The second download is served by the local caches.
        pod.download(&url, digest).await.unwrap();
        assert_eq!(origin_requests.load(Ordering::SeqCst), 1);
    }
}
