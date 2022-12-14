use super::RemoteCacheProvider;
use crate::remote::{
  apply_headers, make_execute_request, populate_fallible_execution_result, EntireExecuteRequest,
};
use crate::Context;
use async_trait::async_trait;
use grpc_util::prost::MessageExt;
use grpc_util::retry::{retry_call, status_is_retryable};
use grpc_util::{headers_to_http_header_map, layered_service, status_to_str, LayeredService};
use hashing::Digest;
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remexec::action_cache_client::ActionCacheClient;
use remexec::{ActionResult, Command, Tree};
use std::fmt;
use std::sync::Arc;
use store::remote::ByteStoreProvider;
use tonic::Request;

#[derive(Clone)]
pub struct RemoteCache {
  instance_name: Option<String>,
  byte_store: Arc<dyn ByteStoreProvider>,
}

impl fmt::Debug for RemoteCache {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "byte_store::RemoteCache(FIXME)")
  }
}

#[async_trait]
impl RemoteCacheProvider for RemoteCache {
  async fn update_action_result(
    &self,
    action_digest: Digest,
    action_result: ActionResult,
  ) -> Result<(), String> {
    let bytes = action_result.to_bytes();
    self
      .byte_store
      .store_bytes(
        Digest {
          hash: action_digest.hash,
          size_bytes: bytes.len(),
        },
        Box::new(move |r| bytes.slice(r)),
      )
      .await
  }
  async fn get_action_result(
    &self,
    action_digest: Digest,
    context: &Context,
  ) -> Result<Option<ActionResult>, String> {
    let result = self.byte_store.load_bytes(action_digest).await?;
    match result {
      Some(bytes) => Ok(Some(
        remexec::ActionResult::decode(bytes).map_err(|err| err.to_string())?,
      )),
      None => Ok(None),
    }
  }
}
