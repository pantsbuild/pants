// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashSet};
use std::fmt;
use std::ops::Range;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bytes::Bytes;
use futures::Future;
use hashing::Digest;
use log::Level;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ServerCapabilities;
use tokio::io::{AsyncSeekExt, AsyncWrite};
use workunit_store::{in_workunit, ObservationMetric};

use crate::StoreError;

mod reapi;
#[cfg(test)]
mod reapi_tests;

pub type ByteSource = Arc<(dyn Fn(Range<usize>) -> Bytes + Send + Sync + 'static)>;

#[async_trait]
pub trait ByteStoreProvider: Sync + Send + 'static {
    async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), String>;

    async fn load(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String>;

    async fn list_missing_digests(
        &self,
        digests: &mut (dyn Iterator<Item = Digest> + Send),
    ) -> Result<HashSet<Digest>, String>;

    fn chunk_size_bytes(&self) -> usize;
}

// TODO: Consider providing `impl Default`, similar to `super::LocalOptions`.
#[derive(Clone)]
pub struct RemoteOptions {
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
pub struct ByteStore {
    instance_name: Option<String>,
    provider: Arc<dyn ByteStoreProvider>,
}

impl fmt::Debug for ByteStore {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "ByteStore(name={:?})", self.instance_name)
    }
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

impl ByteStore {
    pub fn new(
        instance_name: Option<String>,
        provider: Arc<dyn ByteStoreProvider + 'static>,
    ) -> ByteStore {
        ByteStore {
            instance_name,
            provider,
        }
    }

    pub async fn from_options(options: RemoteOptions) -> Result<ByteStore, String> {
        let instance_name = options.instance_name.clone();
        let provider = Arc::new(reapi::Provider::new(options).await?);
        Ok(ByteStore::new(instance_name, provider))
    }

    pub(crate) fn chunk_size_bytes(&self) -> usize {
        self.provider.chunk_size_bytes()
    }

    pub async fn store_buffered<WriteToBuffer, WriteResult>(
        &self,
        digest: Digest,
        write_to_buffer: WriteToBuffer,
    ) -> Result<(), StoreError>
    where
        WriteToBuffer: FnOnce(std::fs::File) -> WriteResult,
        WriteResult: Future<Output = Result<(), StoreError>>,
    {
        let write_buffer = tempfile::tempfile().map_err(|e| {
            format!("Failed to create a temporary blob upload buffer for {digest:?}: {e}")
        })?;
        let read_buffer = write_buffer.try_clone().map_err(|e| {
      format!("Failed to create a read handle for the temporary upload buffer for {digest:?}: {e}")
    })?;
        write_to_buffer(write_buffer).await?;

        // Unsafety: Mmap presents an immutable slice of bytes, but the underlying file that is mapped
        // could be mutated by another process. We guard against this by creating an anonymous
        // temporary file and ensuring it is written to and closed via the only other handle to it in
        // the code just above.
        let mmap = Arc::new(unsafe {
            let mapping = memmap::Mmap::map(&read_buffer).map_err(|e| {
                format!("Failed to memory map the temporary file buffer for {digest:?}: {e}")
            })?;
            if let Err(err) = madvise::madvise(
                mapping.as_ptr(),
                mapping.len(),
                madvise::AccessPattern::Sequential,
            ) {
                log::warn!(
          "Failed to madvise(MADV_SEQUENTIAL) for the memory map of the temporary file buffer for \
          {digest:?}. Continuing with possible reduced performance: {err}",
          digest = digest,
          err = err
        )
            }
            Ok(mapping) as Result<memmap::Mmap, String>
        }?);

        self.store_bytes_source(
            digest,
            Arc::new(move |range| Bytes::copy_from_slice(&mmap[range])),
        )
        .await?;

        Ok(())
    }

    pub async fn store_bytes(&self, bytes: Bytes) -> Result<(), String> {
        let digest = Digest::of_bytes(&bytes);
        self.store_bytes_source(digest, Arc::new(move |range| bytes.slice(range)))
            .await
    }

    async fn store_bytes_source(&self, digest: Digest, bytes: ByteSource) -> Result<(), String> {
        in_workunit!(
            "store_bytes",
            Level::Trace,
            desc = Some(format!("Storing {digest:?}")),
            |workunit| async move {
                let result = self.provider.store_bytes(digest, bytes).await;

                if result.is_ok() {
                    workunit.record_observation(
                        ObservationMetric::RemoteStoreBlobBytesUploaded,
                        digest.size_bytes as u64,
                    );
                }

                result
            }
        )
        .await
    }

    async fn load_monomorphic(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String> {
        let start = Instant::now();
        let workunit_desc = format!(
            "Loading bytes at: {} {} ({} bytes)",
            self.instance_name.as_ref().map_or("", |s| s),
            digest.hash,
            digest.size_bytes
        );

        in_workunit!(
            "load",
            Level::Trace,
            desc = Some(workunit_desc),
            |workunit| async move {
                let result = self.provider.load(digest, destination).await;
                workunit.record_observation(
                    ObservationMetric::RemoteStoreReadBlobTimeMicros,
                    start.elapsed().as_micros() as u64,
                );
                if result.is_ok() {
                    workunit.record_observation(
                        ObservationMetric::RemoteStoreBlobBytesDownloaded,
                        digest.size_bytes as u64,
                    );
                }
                result
            },
        )
        .await
    }

    async fn load<W: LoadDestination>(
        &self,
        digest: Digest,
        mut destination: W,
    ) -> Result<Option<W>, String> {
        if self.load_monomorphic(digest, &mut destination).await? {
            Ok(Some(destination))
        } else {
            Ok(None)
        }
    }

    /// Load the data for `digest` (if it exists in the remote store) into memory.
    pub async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, String> {
        let result = self
            .load(digest, Vec::with_capacity(digest.size_bytes))
            .await?;
        Ok(result.map(Bytes::from))
    }

    /// Write the data for `digest` (if it exists in the remote store) into `file`.
    pub async fn load_file(
        &self,
        digest: Digest,
        file: tokio::fs::File,
    ) -> Result<Option<tokio::fs::File>, String> {
        self.load(digest, file).await
    }

    ///
    /// Given a collection of Digests (digests),
    /// returns the set of digests from that collection not present in the CAS.
    ///
    pub async fn list_missing_digests<I>(&self, digests: I) -> Result<HashSet<Digest>, String>
    where
        I: IntoIterator<Item = Digest>,
        I::IntoIter: Send,
    {
        let mut iter = digests.into_iter();
        in_workunit!(
            "list_missing_digests",
            Level::Trace,
            |_workunit| async move { self.provider.list_missing_digests(&mut iter).await }
        )
        .await
    }
}
