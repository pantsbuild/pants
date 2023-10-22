// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::collections::HashSet;
use std::time::Instant;

use async_trait::async_trait;
use bytes::Bytes;
use futures::future;
use grpc_util::prost::MessageExt;
use hashing::{async_verified_copy, Digest, Fingerprint, EMPTY_DIGEST};
use http::header::AUTHORIZATION;
use opendal::layers::{ConcurrentLimitLayer, RetryLayer, TimeoutLayer};
use opendal::{Builder, Operator};
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ActionResult;
use tokio::fs::File;
use workunit_store::ObservationMetric;

use remote_provider_traits::{
    ActionCacheProvider, ByteStoreProvider, LoadDestination, RemoteOptions,
};

#[cfg(test)]
mod action_cache_tests;
#[cfg(test)]
mod byte_store_tests;

const GITHUB_ACTIONS_CACHE_VERSION: &str = "pants-1";

#[derive(Debug, Clone, Copy)]
pub enum LoadMode {
    Validate,
    NoValidate,
}

pub struct Provider {
    operator: Operator,
    base_path: String,
}

impl Provider {
    pub fn new<B: Builder>(
        builder: B,
        scope: String,
        options: RemoteOptions,
    ) -> Result<Provider, String> {
        let operator = Operator::new(builder)
            .map_err(|e| {
                format!(
                    "failed to initialise {} remote store provider: {e}",
                    B::SCHEME
                )
            })?
            .layer(ConcurrentLimitLayer::new(options.rpc_concurrency_limit))
            .layer(
                // TODO: record Metric::RemoteStoreRequestTimeouts for timeouts
                TimeoutLayer::new()
                    .with_timeout(options.rpc_timeout)
                    // TimeoutLayer requires specifying a non-zero minimum transfer speed too.
                    .with_speed(1),
            )
            // TODO: RetryLayer doesn't seem to retry stores, but we should
            .layer(RetryLayer::new().with_max_times(options.rpc_retries + 1))
            .finish();

        let base_path = match options.instance_name {
            Some(instance_name) => format!("{instance_name}/{scope}"),
            None => scope,
        };

        Ok(Provider {
            operator,
            base_path,
        })
    }

    pub fn fs(path: &str, scope: String, options: RemoteOptions) -> Result<Provider, String> {
        let mut builder = opendal::services::Fs::default();
        builder.root(path).enable_path_check();
        Provider::new(builder, scope, options)
    }

    pub fn github_actions_cache(
        url: &str,
        scope: String,
        options: RemoteOptions,
    ) -> Result<Provider, String> {
        let mut builder = opendal::services::Ghac::default();

        builder.version(GITHUB_ACTIONS_CACHE_VERSION);
        builder.endpoint(url);

        // extract the token from the `authorization: Bearer ...` header because OpenDAL's Ghac service
        // reasons about it separately (although does just stick it in its own `authorization: Bearer
        // ...` header internally).
        let header_help_blurb = "Using GitHub Actions Cache remote cache requires a token set in a `authorization: Bearer ...` header, set via [GLOBAL].remote_store_headers or [GLOBAL].remote_oauth_bearer_token_path";
        let Some(auth_header_value) = options.headers.get(AUTHORIZATION.as_str()) else {
            let existing_headers = options.headers.keys().collect::<Vec<_>>();
            return Err(format!(
                "Expected to find '{}' header, but only found: {:?}. {}",
                AUTHORIZATION, existing_headers, header_help_blurb,
            ));
        };

        let Some(token) = auth_header_value.strip_prefix("Bearer ") else {
            return Err(format!(
                "Expected '{}' header to start with `Bearer `, found value starting with {:?}. {}",
                AUTHORIZATION,
                // only show the first few characters to not accidentally leak (all of) a secret, but
                // still give the user something to start debugging
                &auth_header_value[..4],
                header_help_blurb,
            ));
        };

        builder.runtime_token(token);

        Provider::new(builder, scope, options)
    }

    fn path(&self, fingerprint: Fingerprint) -> String {
        // We include the first two bytes as parent directories to make listings less wide.
        format!(
            "{}/{:02x}/{:02x}/{}",
            self.base_path, fingerprint.0[0], fingerprint.0[1], fingerprint
        )
    }

    async fn load_raw(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
        mode: LoadMode,
    ) -> Result<bool, String> {
        // Some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we just magic
        // it up here, and ignore it when storing.
        if digest == EMPTY_DIGEST {
            // `destination` starts off empty, so is already in the right state.
            return Ok(true);
        }

        let path = self.path(digest.hash);
        let start = Instant::now();
        let mut reader = match self.operator.reader(&path).await {
            Ok(reader) => reader,
            Err(e) if e.kind() == opendal::ErrorKind::NotFound => return Ok(false),
            Err(e) => return Err(format!("failed to read {}: {}", path, e)),
        };

        if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
            // TODO: this pretends that the time-to-first-byte can be approximated by "time to create
            // reader", which is often not really true.
            let timing: Result<u64, _> =
                Instant::now().duration_since(start).as_micros().try_into();
            if let Ok(obs) = timing {
                workunit_store_handle
                    .store
                    .record_observation(ObservationMetric::RemoteStoreTimeToFirstByteMicros, obs);
            }
        }

        match mode {
            LoadMode::Validate => {
                let correct_digest = async_verified_copy(digest, false, &mut reader, destination)
                    .await
                    .map_err(|e| format!("failed to read {}: {}", path, e))?;

                if !correct_digest {
                    // TODO: include the actual digest here
                    return Err(format!("Remote CAS gave wrong digest: expected {digest:?}"));
                }
            }
            LoadMode::NoValidate => {
                tokio::io::copy(&mut reader, destination)
                    .await
                    .map_err(|e| format!("failed to read {}: {}", path, e))?;
            }
        }
        Ok(true)
    }

    /// Load `digest` trusting the contents from the remote, without validating that the digest
    /// matches the downloaded bytes.
    ///
    /// This can/should be used for cases where the digest isn't the digest of the contents
    /// (e.g. action cache).
    pub async fn load_without_validation(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String> {
        self.load_raw(digest, destination, LoadMode::NoValidate)
            .await
    }
}

#[async_trait]
impl ByteStoreProvider for Provider {
    async fn store_bytes(&self, digest: Digest, bytes: Bytes) -> Result<(), String> {
        // Some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we don't
        // store it here, and magic it up when loading.
        if digest == EMPTY_DIGEST {
            return Ok(());
        }

        let path = self.path(digest.hash);

        match self.operator.write(&path, bytes).await {
            Ok(()) => Ok(()),
            // The item already exists, i.e. these bytes have already been stored. For example,
            // concurrent executions that are caching the same bytes. This makes the assumption that
            // which ever execution won the race to create the item successfully finishes the write, and
            // so no wait + retry (or similar) here.
            Err(e) if e.kind() == opendal::ErrorKind::AlreadyExists => Ok(()),
            Err(e) => Err(format!("failed to write bytes to {path}: {e}")),
        }
    }

    async fn store_file(&self, digest: Digest, mut file: File) -> Result<(), String> {
        // Some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we don't
        // store it here, and magic it up when loading.
        if digest == EMPTY_DIGEST {
            return Ok(());
        }

        let path = self.path(digest.hash);

        let mut writer = match self.operator.writer(&path).await {
            Ok(writer) => writer,
            // The item already exists, i.e. these bytes have already been stored. For example,
            // concurrent executions that are caching the same bytes. This makes the assumption that
            // which ever execution won the race to create the item successfully finishes the write, and
            // so no wait + retry (or similar) here.
            Err(e) if e.kind() == opendal::ErrorKind::AlreadyExists => return Ok(()),
            Err(e) => return Err(format!("failed to start write to {path}: {e} {}", e.kind())),
        };

        // TODO: it would be good to pass through options.chunk_size_bytes here
        match tokio::io::copy(&mut file, &mut writer).await {
            Ok(_) => writer.close().await.map_err(|e| {
                format!("Uploading file with digest {digest:?} to {path}: failed to commit: {e}")
            }),
            Err(e) => {
                let abort_err = writer.abort().await.err().map_or("".to_owned(), |e| {
                    format!(" (additional error while aborting = {e})")
                });
                Err(format!(
          "Uploading file with digest {digest:?} to {path}: failed to copy: {e}{abort_err}"
        ))
            }
        }
    }

    async fn load(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String> {
        self.load_raw(digest, destination, LoadMode::Validate).await
    }

    async fn list_missing_digests(
        &self,
        digests: &mut (dyn Iterator<Item = Digest> + Send),
    ) -> Result<HashSet<Digest>, String> {
        // NB. this is doing individual requests and thus may be expensive.
        let existences = future::try_join_all(digests.map(|digest| async move {
            // Some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we don't
            // store it, but can still magic it up when loading, i.e. it is never missing.
            if digest == EMPTY_DIGEST {
                return Ok(None);
            }

            let path = self.path(digest.hash);
            match self.operator.is_exist(&path).await {
                Ok(true) => Ok(None),
                Ok(false) => Ok(Some(digest)),
                Err(e) => Err(format!("failed to query {}: {}", path, e)),
            }
        }))
        .await?;

        Ok(existences.into_iter().flatten().collect())
    }
}

#[async_trait]
impl ActionCacheProvider for Provider {
    async fn update_action_result(
        &self,
        action_digest: Digest,
        action_result: ActionResult,
    ) -> Result<(), String> {
        let bytes = action_result.to_bytes();
        self.store_bytes(action_digest, bytes).await
    }
    async fn get_action_result(
        &self,
        action_digest: Digest,
        _build_id: &str,
    ) -> Result<Option<ActionResult>, String> {
        let mut destination = Vec::new();

        match self
            .load_without_validation(action_digest, &mut destination)
            .await?
        {
            false => Ok(None),
            true => {
                let bytes = Bytes::from(destination);
                Ok(Some(ActionResult::decode(bytes).map_err(|e| {
                    format!("failed to decode action result for digest {action_digest:?}: {e}")
                })?))
            }
        }
    }
}
