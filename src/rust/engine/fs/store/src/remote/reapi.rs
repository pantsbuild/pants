// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::cmp::min;
use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::fmt;
use std::ops::Range;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bytes::{Bytes, BytesMut};
use futures::StreamExt;
use grpc_util::retry::{retry_call, status_is_retryable};
use grpc_util::{headers_to_http_header_map, layered_service, status_to_str, LayeredService};
use hashing::Digest;
use log::Level;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::google::bytestream::byte_stream_client::ByteStreamClient;
use remexec::{
  capabilities_client::CapabilitiesClient,
  content_addressable_storage_client::ContentAddressableStorageClient, BatchUpdateBlobsRequest,
  ServerCapabilities,
};
use tonic::{Code, Request, Status};
use workunit_store::{in_workunit, ObservationMetric};

use crate::remote::{ByteSource, ByteStoreProvider};

#[derive(Clone)]
pub struct ByteStore {
  instance_name: Option<String>,
  chunk_size_bytes: usize,
  _upload_timeout: Duration,
  _rpc_attempts: usize,
  byte_stream_client: Arc<ByteStreamClient<LayeredService>>,
  cas_client: Arc<ContentAddressableStorageClient<LayeredService>>,
  capabilities_cell: Arc<OnceCell<ServerCapabilities>>,
  capabilities_client: Arc<CapabilitiesClient<LayeredService>>,
  batch_api_size_limit: usize,
}

impl fmt::Debug for ByteStore {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "ByteStore(name={:?})", self.instance_name)
  }
}

/// Represents an error from accessing a remote bytestore.
#[derive(Debug)]
pub enum ByteStoreError {
  /// gRPC error
  Grpc(Status),

  /// Other errors
  Other(String),
}

impl fmt::Display for ByteStoreError {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    match self {
      ByteStoreError::Grpc(status) => fmt::Display::fmt(&status_to_str(status), f),
      ByteStoreError::Other(msg) => fmt::Display::fmt(msg, f),
    }
  }
}

impl std::error::Error for ByteStoreError {}

impl ByteStoreError {
  fn retryable(&self) -> bool {
    match self {
      ByteStoreError::Grpc(status) => status_is_retryable(status),
      ByteStoreError::Other(_) => false,
    }
  }
}

impl ByteStore {
  // TODO: Consider extracting these options to a struct with `impl Default`, similar to
  // `super::LocalOptions`.
  #[allow(dead_code)]
  pub fn new(
    cas_address: &str,
    instance_name: Option<String>,
    tls_config: grpc_util::tls::Config,
    mut headers: BTreeMap<String, String>,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    rpc_retries: usize,
    rpc_concurrency_limit: usize,
    capabilities_cell_opt: Option<Arc<OnceCell<ServerCapabilities>>>,
    batch_api_size_limit: usize,
  ) -> Result<ByteStore, String> {
    let tls_client_config = if cas_address.starts_with("https://") {
      Some(tls_config.try_into()?)
    } else {
      None
    };

    let endpoint =
      grpc_util::create_endpoint(cas_address, tls_client_config.as_ref(), &mut headers)?;
    let http_headers = headers_to_http_header_map(&headers)?;
    let channel = layered_service(
      tonic::transport::Channel::balance_list(vec![endpoint].into_iter()),
      rpc_concurrency_limit,
      http_headers,
      None,
    );

    let byte_stream_client = Arc::new(ByteStreamClient::new(channel.clone()));

    let cas_client = Arc::new(ContentAddressableStorageClient::new(channel.clone()));

    let capabilities_client = Arc::new(CapabilitiesClient::new(channel));

    Ok(ByteStore {
      instance_name,
      chunk_size_bytes,
      _upload_timeout: upload_timeout,
      _rpc_attempts: rpc_retries + 1,
      byte_stream_client,
      cas_client,
      capabilities_cell: capabilities_cell_opt.unwrap_or_else(|| Arc::new(OnceCell::new())),
      capabilities_client,
      batch_api_size_limit,
    })
  }

  async fn store_bytes_source_batch<ByteSource>(
    &self,
    digest: Digest,
    bytes: ByteSource,
  ) -> Result<(), ByteStoreError>
  where
    ByteSource: Fn(Range<usize>) -> Bytes + Send + Sync + 'static,
  {
    let request = BatchUpdateBlobsRequest {
      instance_name: self.instance_name.clone().unwrap_or_default(),
      requests: vec![remexec::batch_update_blobs_request::Request {
        digest: Some(digest.into()),
        data: bytes(0..digest.size_bytes),
        compressor: remexec::compressor::Value::Identity as i32,
      }],
    };

    let mut client = self.cas_client.as_ref().clone();
    client
      .batch_update_blobs(request)
      .await
      .map_err(ByteStoreError::Grpc)?;
    Ok(())
  }

  async fn store_bytes_source_stream<ByteSource>(
    &self,
    digest: Digest,
    bytes: ByteSource,
  ) -> Result<(), ByteStoreError>
  where
    ByteSource: Fn(Range<usize>) -> Bytes + Send + Sync + 'static,
  {
    let len = digest.size_bytes;
    let instance_name = self.instance_name.clone().unwrap_or_default();
    let resource_name = format!(
      "{}{}uploads/{}/blobs/{}/{}",
      &instance_name,
      if instance_name.is_empty() { "" } else { "/" },
      uuid::Uuid::new_v4(),
      digest.hash,
      digest.size_bytes,
    );
    let store = self.clone();

    let mut client = self.byte_stream_client.as_ref().clone();

    let chunk_size_bytes = store.chunk_size_bytes;

    let stream = futures::stream::unfold((0, false), move |(offset, has_sent_any)| {
      if offset >= len && has_sent_any {
        futures::future::ready(None)
      } else {
        let next_offset = min(offset + chunk_size_bytes, len);
        let req = protos::gen::google::bytestream::WriteRequest {
          resource_name: resource_name.clone(),
          write_offset: offset as i64,
          finish_write: next_offset == len,
          // TODO(tonic): Explore using the unreleased `Bytes` support in Prost from:
          // https://github.com/danburkert/prost/pull/341
          data: bytes(offset..next_offset),
        };
        futures::future::ready(Some((req, (next_offset, true))))
      }
    });

    // NB: We must box the future to avoid a stack overflow.
    // Explicit type annotation is a workaround for https://github.com/rust-lang/rust/issues/64552
    let x: std::pin::Pin<Box<dyn futures::Future<Output = Result<(), ByteStoreError>> + Send>> =
      Box::pin(async move {
        let response = client
          .write(Request::new(stream))
          .await
          .map_err(ByteStoreError::Grpc)?;

        let response = response.into_inner();
        if response.committed_size == len as i64 {
          Ok(())
        } else {
          Err(ByteStoreError::Other(format!(
            "Uploading file with digest {:?}: want committed size {} but got {}",
            digest, len, response.committed_size
          )))
        }
      });
    x.await
  }

  async fn get_capabilities(&self) -> Result<&remexec::ServerCapabilities, ByteStoreError> {
    let capabilities_fut = async {
      let mut request = remexec::GetCapabilitiesRequest::default();
      if let Some(s) = self.instance_name.as_ref() {
        request.instance_name = s.clone();
      }

      let mut client = self.capabilities_client.as_ref().clone();
      client
        .get_capabilities(request)
        .await
        .map(|r| r.into_inner())
        .map_err(ByteStoreError::Grpc)
    };

    self
      .capabilities_cell
      .get_or_try_init(capabilities_fut)
      .await
  }
}

#[async_trait]
impl ByteStoreProvider for ByteStore {
  fn chunk_size_bytes(&self) -> usize {
    self.chunk_size_bytes
  }

  async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), String> {
    let store = self.clone();
    let len = digest.size_bytes;
    // FIXME: this is nonsense
    let all_bytes = bytes(0..len);

    retry_call(
      all_bytes,
      |all_bytes| async {
        let max_batch_total_size_bytes = {
          let capabilities = store.get_capabilities().await?;

          capabilities
            .cache_capabilities
            .as_ref()
            .map(|c| c.max_batch_total_size_bytes as usize)
            .unwrap_or_default()
        };

        let batch_api_allowed_by_local_config = len <= store.batch_api_size_limit;
        let batch_api_allowed_by_server_config =
          max_batch_total_size_bytes == 0 || len < max_batch_total_size_bytes;

        if batch_api_allowed_by_local_config && batch_api_allowed_by_server_config {
          store
            .store_bytes_source_batch(digest, Box::new(move |r| all_bytes.slice(r)))
            .await?
        } else {
          store
            .store_bytes_source_stream(digest, Box::new(move |r| all_bytes.slice(r)))
            .await?
        }
        Ok(())
      },
      |err: &ByteStoreError| err.retryable(),
    )
    .await
    .map_err(|err| err.to_string())
  }

  async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, String> {
    let store = self.clone();
    let instance_name = store.instance_name.clone().unwrap_or_default();
    let resource_name = format!(
      "{}{}blobs/{}/{}",
      &instance_name,
      if instance_name.is_empty() { "" } else { "/" },
      digest.hash,
      digest.size_bytes
    );

    retry_call(
      (),
      |_| async {
        let mut client = self.byte_stream_client.as_ref().clone();

        let mut start_opt = Some(Instant::now());

        let stream_result = client
          .read({
            protos::gen::google::bytestream::ReadRequest {
              resource_name: resource_name.clone(),
              read_offset: 0,
              // 0 means no limit.
              read_limit: 0,
            }
          })
          .await;

        let mut stream = match stream_result {
          Ok(response) => response.into_inner(),
          Err(status) => {
            return match status.code() {
              Code::NotFound => Ok(None),
              _ => Err(ByteStoreError::Grpc(status)),
            }
          }
        };

        let read_result_closure = async {
          let mut buf = BytesMut::with_capacity(digest.size_bytes);
          while let Some(response) = stream.next().await {
            // Record the observed time to receive the first response for this read.
            if let Some(start) = start_opt.take() {
              if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
                let timing: Result<u64, _> =
                  Instant::now().duration_since(start).as_micros().try_into();
                if let Ok(obs) = timing {
                  workunit_store_handle
                    .store
                    .record_observation(ObservationMetric::RemoteStoreTimeToFirstByteMicros, obs);
                }
              }
            }

            buf.extend_from_slice(&(response?).data);
          }
          Ok(buf.freeze())
        };

        let read_result: Result<Bytes, tonic::Status> = read_result_closure.await;

        match read_result {
          Ok(bytes) => Ok(Some(bytes)),
          Err(status) => {
            if status.code() == tonic::Code::NotFound {
              Ok(None)
            } else {
              Err(ByteStoreError::Grpc(status))
            }
          }
        }
      },
      |err: &ByteStoreError| err.retryable(),
    )
    .await
    .map_err(|err| err.to_string())
  }

  ///
  /// Given a collection of Digests (digests),
  /// returns the set of digests from that collection not present in the CAS.
  ///
  async fn list_missing_digests(
    &self,
    digests: &mut (dyn Iterator<Item = Digest> + Send),
  ) -> Result<Option<HashSet<Digest>>, String> {
    let store = self.clone();
    let request = remexec::FindMissingBlobsRequest {
      instance_name: self.instance_name.as_ref().cloned().unwrap_or_default(),
      blob_digests: digests.into_iter().map(|d| d.into()).collect::<Vec<_>>(),
    };
    in_workunit!(
      "list_missing_digests",
      Level::Trace,
      |_workunit| async move {
        let store2 = store.clone();
        let client = store2.cas_client.as_ref().clone();
        let response = retry_call(
          client,
          move |mut client| {
            let request = request.clone();
            async move { client.find_missing_blobs(request).await }
          },
          status_is_retryable,
        )
        .await
        .map_err(|x| status_to_str(&x))?;

        response
          .into_inner()
          .missing_blob_digests
          .iter()
          .map(|digest| digest.try_into())
          .collect::<Result<HashSet<_>, _>>()
          .map(Some)
      }
    )
    .await
  }
}
