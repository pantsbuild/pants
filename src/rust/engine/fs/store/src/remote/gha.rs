// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use async_trait::async_trait;
use bytes::Bytes;
use hashing::Digest;
use opendal::services::ghac;
use opendal::{ErrorKind, Operator};

use crate::remote::{ByteSource, ByteStoreProvider};

pub struct ByteStore {
  operator: Operator,
}

const GHA_STORE_VERSION: &str = "pants-gha-1";

impl ByteStore {
  pub fn new(cache_key: &str) -> Result<ByteStore, String> {
    Ok(ByteStore {
      operator: Operator::new(
        ghac::Builder::default()
          .version(GHA_STORE_VERSION)
          .root(cache_key)
          .build()
          .map_err(|e| e.to_string())?,
      ),
    })
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
    log::debug!("storing {} ({} bytes)", digest.hash, digest.size_bytes,);
    let slice = if digest.size_bytes == 0 {
      Bytes::from(EMPTY_BYTES)
    } else {
      // FIXME: it'd be better to have this implement Read directly
      bytes(0..digest.size_bytes)
    };

    let object = self.operator.object(&digest.hash.to_string());
    object
      .write_from(digest.size_bytes as u64, futures::io::Cursor::new(slice))
      .await
      .map_err(|e| e.to_string())?;
    Ok(())
  }
  async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, String> {
    log::debug!("loading {} ({} bytes)", digest.hash, digest.size_bytes,);
    let object = self.operator.object(&digest.hash.to_string());
    match object.read().await {
      Ok(data) if digest.size_bytes == 0 && data == EMPTY_BYTES => Ok(Some(Bytes::new())),
      Ok(data) => Ok(Some(Bytes::from(data))),
      Err(err) if err.kind() == ErrorKind::ObjectNotFound => Ok(None),
      Err(err) => Err(err.to_string()),
    }
  }
}

// FIXME: I think this is only used for digest caches, not process executions, see src/rust/engine/process_execution/src/remote.rs and src/rust/engine/process_execution/src/remote_cache.rs
