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

use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bytes::Bytes;
use hashing::Digest;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::{ActionResult, ServerCapabilities};
use tokio::fs::File;
use tokio::io::{AsyncSeekExt, AsyncWrite};

// TODO: Consider providing `impl Default`, similar to `remote::LocalOptions`.
#[derive(Clone)]
pub struct RemoteOptions {
    // TODO: this is currently framed for the REAPI provider, with some options used by others, would
    // be good to generalise
    pub cas_address: String,
    pub instance_name: Option<String>,
    pub headers: BTreeMap<String, String>,
    pub tls_config: grpc_util::tls::Config,
    pub chunk_size_bytes: usize,
    pub rpc_timeout: Duration,
    pub rpc_retries: usize,
    pub rpc_concurrency_limit: usize,
    pub capabilities_cell_opt: Option<Arc<OnceCell<ServerCapabilities>>>,
    pub batch_api_size_limit: usize,
}

#[derive(Clone)]
pub struct RemoteCacheProviderOptions {
    // TODO: this is currently framed for the REAPI provider, with some options used by others, would
    // be good to generalise
    // TODO: this is structurally very similar to `RemoteOptions`: maybe they should be the same? (see
    // comment in `choose_action_cache_provider` too)
    pub instance_name: Option<String>,
    pub action_cache_address: String,
    pub tls_config: grpc_util::tls::Config,
    pub headers: BTreeMap<String, String>,
    pub concurrency_limit: usize,
    pub rpc_timeout: Duration,
}

#[async_trait]
pub trait ByteStoreProvider: Sync + Send + 'static {
    /// Store the bytes readable from `file` into the remote store
    async fn store_file(&self, digest: Digest, file: File) -> Result<(), String>;

    /// Store the bytes in `bytes` into the remote store, as an optimisation of `store_file` when the
    /// bytes are already in memory
    async fn store_bytes(&self, digest: Digest, bytes: Bytes) -> Result<(), String>;

    /// Load the data stored (if any) in the remote store for `digest` into `destination`. Returns
    /// true when found, false when not.
    async fn load(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String>;

    /// Return any digests from `digests` that are not (currently) available in the remote store.
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
