// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashSet;
use std::fmt;
use std::ops::Range;
use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;
use bytes::Bytes;
use futures::Future;
use hashing::Digest;
use log::Level;
use workunit_store::{in_workunit, ObservationMetric};

use crate::StoreError;

pub mod gha;
pub mod reapi;

pub type ByteSource = Box<(dyn Fn(Range<usize>) -> Bytes + Send + Sync + 'static)>;

#[async_trait]
pub trait ByteStoreProvider: Sync {
  async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), String>;
  async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, String>;

  /// List any missing digests.
  ///
  /// None = not supported.
  async fn list_missing_digests(
    &self,
    _digests: &mut (dyn Iterator<Item = Digest> + Send),
  ) -> Result<Option<HashSet<Digest>>, String> {
    Ok(None)
  }

  fn chunk_size_bytes(&self) -> usize;
}

#[derive(Clone)]
pub(crate) struct ByteStore {
  connection: Arc<dyn ByteStoreProvider + Sync + Send + 'static>,
}

impl fmt::Debug for ByteStore {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "ByteStore(FIXME)")
  }
}

impl ByteStore {
  pub fn new(connection: impl ByteStoreProvider + Sync + Send + 'static) -> ByteStore {
    ByteStore {
      connection: Arc::new(connection),
    }
  }

  pub(crate) fn chunk_size_bytes(&self) -> usize {
    self.connection.chunk_size_bytes()
  }

  pub async fn store_buffered<WriteToBuffer, WriteResult>(
    &self,
    digest: Digest,
    mut write_to_buffer: WriteToBuffer,
  ) -> Result<(), StoreError>
  where
    WriteToBuffer: FnMut(std::fs::File) -> WriteResult,
    WriteResult: Future<Output = Result<(), StoreError>>,
  {
    let write_buffer = tempfile::tempfile().map_err(|e| {
      format!(
        "Failed to create a temporary blob upload buffer for {digest:?}: {err}",
        digest = digest,
        err = e
      )
    })?;
    let read_buffer = write_buffer.try_clone().map_err(|e| {
      format!(
        "Failed to create a read handle for the temporary upload buffer for {digest:?}: {err}",
        digest = digest,
        err = e
      )
    })?;
    write_to_buffer(write_buffer).await?;

    // Unsafety: Mmap presents an immutable slice of bytes, but the underlying file that is mapped
    // could be mutated by another process. We guard against this by creating an anonymous
    // temporary file and ensuring it is written to and closed via the only other handle to it in
    // the code just above.
    let mmap = Arc::new(unsafe {
      let mapping = memmap::Mmap::map(&read_buffer).map_err(|e| {
        format!(
          "Failed to memory map the temporary file buffer for {digest:?}: {err}",
          digest = digest,
          err = e
        )
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

    self
      .store_bytes_source(
        digest,
        Box::new(move |range| Bytes::copy_from_slice(&mmap[range])),
      )
      .await?;

    Ok(())
  }

  pub async fn store_bytes(&self, bytes: Bytes) -> Result<(), String> {
    let digest = Digest::of_bytes(&bytes);
    self
      .store_bytes_source(digest, Box::new(move |range| bytes.slice(range)))
      .await
  }

  async fn store_bytes_source(&self, digest: Digest, bytes: ByteSource) -> Result<(), String> {
    log::trace!("remote_trait::ByteStore::store_bytes_source({:?})", digest);
    let len = digest.size_bytes;

    in_workunit!(
      "store_bytes",
      Level::Trace,
      desc = Some(format!("Storing {digest:?}")),
      |workunit| async move {
        let result = self.connection.store_bytes(digest, bytes).await;

        if result.is_ok() {
          workunit.record_observation(ObservationMetric::RemoteStoreBlobBytesUploaded, len as u64);
        }

        result
      }
    )
    .await
  }

  pub async fn load_bytes_with<
    T: Send + 'static,
    F: Fn(Bytes) -> Result<T, String> + Send + Sync + Clone + 'static,
  >(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String> {
    log::trace!("remote_trait::ByteStore::load_bytes_with({:?})", digest);
    let start = Instant::now();
    let workunit_desc = format!("Loading {} bytes for {}", digest.size_bytes, digest.hash);
    let result_future = async move {
      match self.connection.load_bytes(digest).await {
        Ok(Some(bytes)) => Ok(Some(f(bytes)?)),
        Ok(None) => Ok(None),
        Err(err) => Err(err),
      }
    };

    in_workunit!(
      "load_bytes_with",
      Level::Trace,
      desc = Some(workunit_desc),
      |workunit| async move {
        let result = result_future.await;
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
      }
    )
    .await
  }

  pub async fn list_missing_digests<D>(&self, digests: D) -> Result<Option<HashSet<Digest>>, String>
  where
    D: IntoIterator<Item = Digest> + Send,
    D::IntoIter: Send,
  {
    log::trace!("remote_trait::ByteStore::list_missing_digests running...");
    in_workunit!(
      "list_missing_digests",
      Level::Trace,
      |_workunit| async move {
        self
          .connection
          .list_missing_digests(&mut digests.into_iter())
          .await
      }
    )
    .await
  }
}
