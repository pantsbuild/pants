// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;
use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use deepsize::DeepSizeOf;
use fs::RelativePath;
use graph::CompoundNode;
use grpc_util::prost::MessageExt;
use hashing::Digest;
use protos::gen::pants::cache::{CacheKey, CacheKeyType, ObservedUrl};
use pyo3::prelude::Python;
use url::Url;

use super::{NodeKey, NodeResult};
use crate::context::{Context, Core};
use crate::downloads;
use crate::externs;
use crate::externs::fs::PyFileDigest;
use crate::python::{throw, Key};

#[derive(Clone, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct DownloadedFile(pub Key);

impl DownloadedFile {
    fn url_key(url: &Url, digest: Digest) -> CacheKey {
        let observed_url = ObservedUrl {
            url: url.as_str().to_owned(),
            observed_digest: Some(digest.into()),
        };
        CacheKey {
            key_type: CacheKeyType::Url.into(),
            digest: Some(Digest::of_bytes(&observed_url.to_bytes()).into()),
        }
    }

    pub async fn load_or_download(
        &self,
        core: Arc<Core>,
        url: Url,
        auth_headers: BTreeMap<String, String>,
        digest: hashing::Digest,
        retry_delay_duration: Duration,
        max_attempts: NonZeroUsize,
    ) -> Result<store::Snapshot, String> {
        let file_name = url
            .path_segments()
            .and_then(Iterator::last)
            .map(str::to_owned)
            .ok_or_else(|| format!("Error getting the file name from the parsed URL: {url}"))?;
        let path = RelativePath::new(&file_name).map_err(|e| {
            format!(
                "The file name derived from {} was {} which is not relative: {:?}",
                &url, &file_name, e
            )
        })?;

        // See if we have observed this URL and Digest before: if so, see whether we already have the
        // Digest fetched. The extra layer of indirection through the PersistentCache is to sanity
        // check that a Digest has ever been observed at the given URL.
        // NB: The auth_headers are not part of the key.
        let url_key = Self::url_key(&url, digest);
        let have_observed_url = core.local_cache.load(&url_key).await?.is_some();

        // If we hit the ObservedUrls cache, then we have successfully fetched this Digest from
        // this URL before. If we still have the bytes, then we skip fetching the content again.
        let usable_in_store = have_observed_url
            && (core
                .store()
                .load_file_bytes_with(digest, |_| ())
                .await
                .is_ok());

        if !usable_in_store {
            downloads::download(
                &core.http_client,
                core.store(),
                url,
                auth_headers,
                file_name,
                digest,
                retry_delay_duration,
                max_attempts,
            )
            .await?;
            // The value was successfully fetched and matched the digest: record in the ObservedUrls
            // cache.
            core.local_cache.store(&url_key, Bytes::from("")).await?;
        }
        core.store().snapshot_of_one_file(path, digest, true).await
    }

    pub(super) async fn run_node(self, context: Context) -> NodeResult<store::Snapshot> {
        let (url_str, expected_digest, auth_headers, retry_delay_duration, max_attempts) =
            Python::with_gil(|py| {
                let py_download_file_val = self.0.to_value();
                let py_download_file = (*py_download_file_val).as_ref(py);
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
        self.load_or_download(
            context.core.clone(),
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
