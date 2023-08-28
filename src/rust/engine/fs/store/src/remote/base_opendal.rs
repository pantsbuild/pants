#![allow(dead_code)]

use async_trait::async_trait;
use bytes::Bytes;
use hashing::{async_verified_copy, Digest, Fingerprint};
use opendal::Operator;
use std::collections::HashSet;
use tokio::fs::File;

use super::{ByteStoreProvider, LoadDestination};

pub struct Provider {
  pub(crate) op: Operator,
  base_path: String,
}

impl Provider {
  pub fn new(op: Operator, base_path: String) -> Provider {
    // FIXME: validate base_path
    Provider { op, base_path }
  }

  fn path(&self, fingerprint: Fingerprint) -> String {
    format!("{}/{}", self.base_path, fingerprint)
  }
}

#[async_trait]
impl ByteStoreProvider for Provider {
  async fn store_bytes(&self, _digest: Digest, _bytes: Bytes) -> Result<(), String> {
    unimplemented!()
  }

  async fn store_file(&self, _digest: Digest, _file: File) -> Result<(), String> {
    unimplemented!()
  }

  async fn load(
    &self,
    digest: Digest,
    destination: &mut dyn LoadDestination,
  ) -> Result<bool, String> {
    let path = self.path(digest.hash);
    let mut reader = self
      .op
      .reader(&path)
      .await
      .map_err(|e| format!("failed to read {}: {}", path, e))?;
    // FIXME: retries
    async_verified_copy(digest, false, &mut reader, destination)
      .await
      .map_err(|e| format!("failed to read {}: {}", path, e))
  }

  async fn list_missing_digests(
    &self,
    _digests: &mut (dyn Iterator<Item = Digest> + Send),
  ) -> Result<HashSet<Digest>, String> {
    unimplemented!()
  }
}
