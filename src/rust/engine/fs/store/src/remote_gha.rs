// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use async_trait::async_trait;
use bytes::Bytes;
use gha_toolkit::cache::{ArtifactCacheEntry, CacheClient};
use hashing::Digest;

use crate::remote_trait::{ByteSource, RemoteCacheConnection, RemoteCacheError};

pub struct ByteStore {
  client: CacheClient,
}

impl ByteStore {
  pub fn new(base_url: &str, token: &str, cache_prefix: &str) -> Result<ByteStore, String> {
    Ok(ByteStore {
      client: CacheClient::builder(base_url, token)
        .cache_to(cache_prefix)
        .build()
        .map_err(|err| err.to_string())?,
    })
  }

  fn version_for_digest(&self, digest: &Digest) -> String {
    digest.hash.to_hex()
  }
}

#[async_trait]
impl RemoteCacheConnection for ByteStore {
  fn chunk_size_bytes(&self) -> usize {
    usize::MAX
  }

  async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), RemoteCacheError> {
    log::debug!(
      "storing {} ({} bytes) via {}",
      digest.hash,
      digest.size_bytes,
      self.client.base_url()
    );
    let slice = bytes(0..digest.size_bytes);
    self
      .client
      .put(
        &self.version_for_digest(&digest),
        std::io::Cursor::new(slice),
      )
      .await
      .map_err(|err| RemoteCacheError {
        retryable: false,
        msg: err.to_string(),
      })?;
    Ok(())
  }
  async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, RemoteCacheError> {
    log::debug!(
      "loading {} ({} bytes) via {}",
      digest.hash,
      digest.size_bytes,
      self.client.base_url()
    );
    let entry = self
      .client
      .entry(&self.version_for_digest(&digest))
      .await
      .map_err(|err| RemoteCacheError {
        retryable: false,
        msg: err.to_string(),
      })?;
    if let Some(ArtifactCacheEntry {
      archive_location: Some(url),
      ..
    }) = entry
    {
      let data = self
        .client
        .get(&url)
        .await
        .map_err(|err| RemoteCacheError {
          retryable: false,
          msg: err.to_string(),
        })?;
      Ok(Some(Bytes::from(data)))
    } else {
      Ok(None)
    }
  }
}
