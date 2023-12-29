// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, HashSet};
use std::time::Duration;

use async_trait::async_trait;
use bytes::Bytes;
use hashing::Digest;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ActionResult;
use tokio::fs::File;
use tokio::io::{AsyncSeekExt, AsyncWrite};

// TODO: this is duplicated with global_options.py, it'd be good to have this be the single source
// of truth.
#[derive(Clone, Copy, Debug, strum_macros::EnumString)]
#[strum(serialize_all = "kebab-case")]
pub enum RemoteProvider {
    Reapi,
    ExperimentalFile,
    ExperimentalGithubActionsCache,
}

// TODO: Consider providing `impl Default`, similar to `remote::LocalOptions`.
#[derive(Clone)]
pub struct RemoteStoreOptions {
    // TODO: this is currently framed for the REAPI provider, with some options used by others, would
    // be good to generalise
    pub store_address: String,
    pub instance_name: Option<String>,
    pub headers: BTreeMap<String, String>,
    pub tls_config: grpc_util::tls::Config,
    pub chunk_size_bytes: usize,
    pub timeout: Duration,
    pub retries: usize,
    pub concurrency_limit: usize,
    pub batch_api_size_limit: usize,
}

#[async_trait]
pub trait ByteStoreProvider: Sync + Send + 'static {
    /// Store the bytes readable from `file` into the remote store
    ///
    /// NB. this does not need to update any observations or counters.
    async fn store_file(&self, digest: Digest, file: File) -> Result<(), String>;

    /// Store the bytes in `bytes` into the remote store, as an optimisation of `store_file` when the
    /// bytes are already in memory
    ///
    /// NB. this does not need to update any observations or counters.
    async fn store_bytes(&self, digest: Digest, bytes: Bytes) -> Result<(), String>;

    /// Load the data stored (if any) in the remote store for `digest` into `destination`. Returns
    /// true when found, false when not.
    ///
    /// NB. this should update the
    /// workunit_store::ObservationMetric::RemoteStoreTimeToFirstByteMicros observation.
    async fn load(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String>;

    /// Return any digests from `digests` that are not (currently) available in the remote store.
    ///
    /// NB. this should update the workunit_store::Metric::RemoteStoreExists... counters, based on
    /// the requests it runs.
    async fn list_missing_digests(
        &self,
        digests: &mut (dyn Iterator<Item = Digest> + Send),
    ) -> Result<HashSet<Digest>, String>;
}

/// Places that write the result of a remote `load`
#[async_trait]
pub trait LoadDestination: AsyncWrite + Send + Sync + Unpin + 'static {
    /// Clear out the writer and start again, if there's been previous contents written
    async fn reset(&mut self) -> std::io::Result<()>;
}

#[async_trait]
impl LoadDestination for tokio::fs::File {
    async fn reset(&mut self) -> std::io::Result<()> {
        self.rewind().await?;
        self.set_len(0).await
    }
}

#[async_trait]
impl LoadDestination for Vec<u8> {
    async fn reset(&mut self) -> std::io::Result<()> {
        self.clear();
        Ok(())
    }
}

/// This `ActionCacheProvider` trait captures the operations required to be able to cache command
/// executions remotely.
#[async_trait]
pub trait ActionCacheProvider: Sync + Send + 'static {
    async fn update_action_result(
        &self,
        action_digest: Digest,
        action_result: ActionResult,
    ) -> Result<(), String>;

    async fn get_action_result(
        &self,
        action_digest: Digest,
        build_id: &str,
    ) -> Result<Option<ActionResult>, String>;
}
