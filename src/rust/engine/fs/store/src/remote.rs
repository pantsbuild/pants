// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashSet;
use std::fmt;
use std::sync::Arc;
use std::time::Instant;

use bytes::Bytes;
use futures::Future;
use hashing::Digest;
use log::Level;
use remote_provider::{
  choose_byte_store_provider, ByteStoreProvider, LoadDestination, RemoteOptions,
};
use tokio::fs::File;
use workunit_store::{in_workunit, ObservationMetric};

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
    let provider = choose_byte_store_provider(options).await?;
    Ok(ByteStore::new(instance_name, provider))
  }

  /// Store the bytes readable from `file` into the remote store
  pub async fn store_file(&self, digest: Digest, file: File) -> Result<(), String> {
    self
      .store_tracking("store", digest, || self.provider.store_file(digest, file))
      .await
  }

  /// Store the bytes in `bytes` into the remote store, as an optimisation of `store_file` when the
  /// bytes are already in memory
  pub async fn store_bytes(&self, bytes: Bytes) -> Result<(), String> {
    let digest = Digest::of_bytes(&bytes);
    self
      .store_tracking("store_bytes", digest, || {
        self.provider.store_bytes(digest, bytes)
      })
      .await
  }

  async fn store_tracking<DoStore, Fut>(
    &self,
    workunit: &'static str,
    digest: Digest,
    do_store: DoStore,
  ) -> Result<(), String>
  where
    DoStore: FnOnce() -> Fut + Send,
    Fut: Future<Output = Result<(), String>> + Send,
  {
    in_workunit!(
      workunit,
      Level::Trace,
      desc = Some(format!("Storing {digest:?}")),
      |workunit| async move {
        let result = do_store().await;

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
