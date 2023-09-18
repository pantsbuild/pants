// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
#![allow(dead_code)]

use std::collections::HashSet;
use std::time::Instant;

use async_trait::async_trait;
use bytes::Bytes;
use futures::future;
use hashing::{async_verified_copy, Digest, Fingerprint, EMPTY_DIGEST};
use opendal::layers::{ConcurrentLimitLayer, RetryLayer, TimeoutLayer};
use opendal::{Builder, Operator};
use tokio::fs::File;
use workunit_store::ObservationMetric;

use super::{ByteStoreProvider, LoadDestination, RemoteOptions};

#[derive(Debug, Clone, Copy)]
pub enum LoadMode {
  Validate,
  NoValidate,
}

pub struct Provider {
  /// This is public for easier testing of the action cache provider
  // TODO: move all the providers into a single crate so that the pub isn't necessary
  pub operator: Operator,
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
          // TimeoutLayer requires specifying a non-zero minimum transfer speed too
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

  fn path(&self, fingerprint: Fingerprint) -> String {
    // include the two bytes as parent directories to make listings less wide
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
    // some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we just magic
    // it up here, and ignore it when storing
    if digest == EMPTY_DIGEST {
      // destination starts off empty, so is already in the right state
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
      let timing: Result<u64, _> = Instant::now().duration_since(start).as_micros().try_into();
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
    self
      .load_raw(digest, destination, LoadMode::NoValidate)
      .await
  }
}

#[async_trait]
impl ByteStoreProvider for Provider {
  async fn store_bytes(&self, digest: Digest, bytes: Bytes) -> Result<(), String> {
    // some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we don't
    // store it here, and magic it up when loading
    if digest == EMPTY_DIGEST {
      return Ok(());
    }

    let path = self.path(digest.hash);

    self
      .operator
      .write(&path, bytes)
      .await
      .map_err(|e| format!("failed to write bytes to {path}: {e}"))
  }

  async fn store_file(&self, digest: Digest, mut file: File) -> Result<(), String> {
    // some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we don't
    // store it here, and magic it up when loading
    if digest == EMPTY_DIGEST {
      return Ok(());
    }

    let path = self.path(digest.hash);

    let mut writer = self
      .operator
      .writer_with(&path)
      .content_length(digest.size_bytes as u64)
      .await
      .map_err(|e| format!("failed to start write to {path}: {e}"))?;

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
    // NB. this is doing individual requests and thus may be expensive
    let existences = future::try_join_all(digests.map(|digest| async move {
      // some providers (e.g. GitHub Actions Cache) don't like storing an empty file, so we don't
      // store it, but can still magic it up when loading, i.e. it is never missing
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
