// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use async_trait::async_trait;
use bytes::Bytes;
use gha_toolkit::cache::{ArtifactCacheEntry, CacheClient};
use hashing::Digest;

use crate::remote::{ByteSource, ByteStoreProvider};

pub struct ByteStore {
  client: CacheClient,
}

impl ByteStore {
  pub fn new(base_url: &str, token: &str, cache_key: &str) -> Result<ByteStore, String> {
    Ok(ByteStore {
      client: CacheClient::builder(base_url, token)
        .cache_to(cache_key)
        .cache_from([cache_key].iter().copied())
        .build()
        .map_err(|err| err.to_string())?,
    })
  }

  fn version_for_digest(&self, digest: &Digest) -> String {
    digest.hash.to_hex()
  }
}

// GHA doesn't support storing empty caches, so we swap in
const EMPTY_BYTES: &[u8] = &[0xFF];

#[async_trait]
impl ByteStoreProvider for ByteStore {
  fn chunk_size_bytes(&self) -> usize {
    usize::MAX
  }

  async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), String> {
    log::debug!(
      "storing {} ({} bytes) via {}",
      digest.hash,
      digest.size_bytes,
      self.client.base_url()
    );
    let slice = if digest.size_bytes == 0 {
      Bytes::from(EMPTY_BYTES)
    } else {
      bytes(0..digest.size_bytes)
    };

    self
      .client
      .put(
        &self.version_for_digest(&digest),
        std::io::Cursor::new(slice),
      )
      .await
      .map_err(|err| err.to_string())?;
    Ok(())
  }
  async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, String> {
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
      .map_err(|err| err.to_string())?;
    if let Some(ArtifactCacheEntry {
      archive_location: Some(url),
      ..
    }) = entry
    {
      let data = self.client.get(&url).await.map_err(|err| err.to_string())?;
      Ok(Some(if digest.size_bytes == 0 && data == EMPTY_BYTES {
        Bytes::new()
      } else {
        Bytes::from(data)
      }))
    } else {
      Ok(None)
    }
  }
}

// FIXME: I think this is only used for digest caches, not process executions, see src/rust/engine/process_execution/src/remote.rs and src/rust/engine/process_execution/src/remote_cache.rs
