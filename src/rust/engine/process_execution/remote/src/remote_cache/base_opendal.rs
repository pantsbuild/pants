// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
#![allow(dead_code)]

use async_trait::async_trait;
use bytes::Bytes;
use grpc_util::prost::MessageExt;
use hashing::Digest;
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::ActionResult;

use super::ActionCacheProvider;
use process_execution::Context;
use remote_provider_traits::ByteStoreProvider;

pub use store::remote::base_opendal::Provider;

#[async_trait]
impl ActionCacheProvider for Provider {
  async fn update_action_result(
    &self,
    action_digest: Digest,
    action_result: ActionResult,
  ) -> Result<(), String> {
    let bytes = action_result.to_bytes();
    self.store_bytes(action_digest, bytes).await
  }
  async fn get_action_result(
    &self,
    action_digest: Digest,
    _context: &Context,
  ) -> Result<Option<ActionResult>, String> {
    let mut destination = Vec::new();

    match self
      .load_without_validation(action_digest, &mut destination)
      .await?
    {
      false => Ok(None),
      true => {
        let bytes = Bytes::from(destination);
        Ok(Some(ActionResult::decode(bytes).map_err(|e| {
          format!("failed to decode action result for digest {action_digest:?}: {e}")
        })?))
      }
    }
  }
}
