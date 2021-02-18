use std::cmp::min;
use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::fmt;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::gen::google::bytestream::byte_stream_client::ByteStreamClient;
use bazel_protos::{self};
use bytes::{Bytes, BytesMut};
use futures::future::TryFutureExt;
use futures::Future;
use futures::StreamExt;
use grpc_util::headers_to_interceptor_fn;
use hashing::Digest;
use itertools::{Either, Itertools};
use log::Level;
use remexec::content_addressable_storage_client::ContentAddressableStorageClient;
use tonic::transport::{Channel, Endpoint};
use tonic::{Code, Interceptor, Request};
use workunit_store::{with_workunit, ObservationMetric};

use super::BackoffConfig;

#[derive(Clone)]
pub struct ByteStore {
  instance_name: Option<String>,
  chunk_size_bytes: usize,
  upload_timeout: Duration,
  rpc_attempts: usize,
  channel: Channel,
  interceptor: Option<Interceptor>,
  byte_stream_client: Arc<ByteStreamClient<Channel>>,
  cas_client: Arc<ContentAddressableStorageClient<Channel>>,
}

impl fmt::Debug for ByteStore {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(f, "ByteStore(name={:?})", self.instance_name)
  }
}

impl ByteStore {
  pub fn new(
    cas_addresses: Vec<String>,
    instance_name: Option<String>,
    root_ca_certs: Option<Vec<u8>>,
    headers: BTreeMap<String, String>,
    _thread_count: usize,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    _backoff_config: BackoffConfig,
    rpc_retries: usize,
    _connection_limit: usize,
  ) -> Result<ByteStore, String> {
    let tls_client_config = if cas_addresses
      .first()
      .map(|addr| addr.starts_with("https://"))
      .unwrap_or(false)
    {
      Some(grpc_util::create_tls_config(root_ca_certs)?)
    } else {
      None
    };

    let (endpoints, errors): (Vec<Endpoint>, Vec<String>) = cas_addresses
      .iter()
      .map(|addr| grpc_util::create_endpoint(addr, tls_client_config.as_ref()))
      .partition_map(|result| match result {
        Ok(endpoint) => Either::Left(endpoint),
        Err(err) => Either::Right(err),
      });

    if !errors.is_empty() {
      return Err(format!(
        "Errors while creating gRPC endpoints: {}",
        errors.join(", ")
      ));
    }

    let channel = tonic::transport::Channel::balance_list(endpoints.iter().cloned());
    let interceptor = if headers.is_empty() {
      None
    } else {
      Some(Interceptor::new(headers_to_interceptor_fn(&headers)?))
    };

    let byte_stream_client = Arc::new(match interceptor.as_ref() {
      Some(interceptor) => ByteStreamClient::with_interceptor(channel.clone(), interceptor.clone()),
      None => ByteStreamClient::new(channel.clone()),
    });

    let cas_client = Arc::new(match interceptor.as_ref() {
      Some(interceptor) => {
        ContentAddressableStorageClient::with_interceptor(channel.clone(), interceptor.clone())
      }
      None => ContentAddressableStorageClient::new(channel.clone()),
    });

    Ok(ByteStore {
      instance_name,
      chunk_size_bytes,
      upload_timeout,
      channel,
      rpc_attempts: rpc_retries + 1,
      interceptor,
      byte_stream_client,
      cas_client,
    })
  }

  pub async fn store_bytes(&self, bytes: &[u8]) -> Result<Digest, String> {
    let len = bytes.len();
    let digest = Digest::of_bytes(&bytes);
    let resource_name = format!(
      "{}/uploads/{}/blobs/{}/{}",
      self.instance_name.clone().unwrap_or_default(),
      uuid::Uuid::new_v4(),
      digest.hash,
      digest.size_bytes,
    );
    let workunit_name = format!("store_bytes({})", resource_name.clone());
    let metadata = workunit_store::WorkunitMetadata::with_level(Level::Debug);
    let store = self.clone();

    let mut client = self.byte_stream_client.as_ref().clone();

    let resource_name = resource_name.clone();
    let chunk_size_bytes = store.chunk_size_bytes;

    // NOTE(tonic): The call into the Tonic library wants the slice to last for the 'static
    // lifetime but the slice passed into this method generally points into the shared memory
    // of the LMDB store which is on the other side of the FFI boundary.
    let bytes = Bytes::copy_from_slice(bytes);

    let stream = futures::stream::unfold((0, false), move |(offset, has_sent_any)| {
      if offset >= bytes.len() && has_sent_any {
        futures::future::ready(None)
      } else {
        let next_offset = min(offset + chunk_size_bytes, bytes.len());
        let req = bazel_protos::gen::google::bytestream::WriteRequest {
          resource_name: resource_name.clone(),
          write_offset: offset as i64,
          finish_write: next_offset == bytes.len(),
          // TODO(tonic): Explore using the unreleased `Bytes` support in Prost from:
          // https://github.com/danburkert/prost/pull/341
          data: bytes.slice(offset..next_offset),
        };
        futures::future::ready(Some((req, (next_offset, true))))
      }
    });

    // NOTE: This async closure must be boxed or else it triggers a consistent stack overflow
    // when awaited with the `with_workunit` call below.
    let result_future = Box::pin(async move {
      let response = client.write(Request::new(stream)).await.map_err(|err| {
        format!(
          "Error from server while uploading digest {:?}: {:?}",
          digest, err
        )
      })?;

      let response = response.into_inner();
      if response.committed_size == len as i64 {
        Ok(digest)
      } else {
        Err(format!(
          "Uploading file with digest {:?}: want committed size {} but got {}",
          digest, len, response.committed_size
        ))
      }
    });

    if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
      let workunit_store = workunit_store_handle.store;
      with_workunit(
        workunit_store,
        workunit_name,
        metadata,
        result_future,
        |_, md| md,
      )
      .await
    } else {
      result_future.await
    }
  }

  pub async fn load_bytes_with<
    T: Send + 'static,
    F: Fn(Bytes) -> Result<T, String> + Send + Sync + Clone + 'static,
  >(
    &self,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String> {
    let store = self.clone();
    let resource_name = format!(
      "{}/blobs/{}/{}",
      store.instance_name.clone().unwrap_or_default(),
      digest.hash,
      digest.size_bytes
    );
    let workunit_name = format!("load_bytes_with({})", resource_name.clone());
    let metadata = workunit_store::WorkunitMetadata::with_level(Level::Debug);
    let resource_name = resource_name.clone();
    let f = f.clone();

    let mut client = self.byte_stream_client.as_ref().clone();

    let result_future = async move {
      let start_time = Instant::now();

      let stream_result = client
        .read({
          bazel_protos::gen::google::bytestream::ReadRequest {
            resource_name: resource_name.clone(),
            read_offset: 0,
            // 0 means no limit.
            read_limit: 0,
          }
        })
        .await;

      let mut stream = match stream_result {
        Ok(response) => response.into_inner(),
        Err(status) => match status.code() {
          Code::NotFound => return Ok(None),
          _ => {
            return Err(format!(
              "Error making CAS read request for {:?}: {:?}",
              digest, status
            ))
          }
        },
      };

      let read_result_closure = async {
        let mut got_first_response = false;
        let mut buf = BytesMut::with_capacity(digest.size_bytes);
        while let Some(response) = stream.next().await {
          // Record the observed time to receive the first response for this read.
          if !got_first_response {
            got_first_response = true;

            if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
              let timing: Result<u64, _> = Instant::now()
                .duration_since(start_time)
                .as_micros()
                .try_into();
              if let Ok(obs) = timing {
                workunit_store_handle
                  .store
                  .record_observation(ObservationMetric::RemoteStoreTimeToFirstByte, obs);
              }
            }
          }

          buf.extend_from_slice(&(response?).data);
        }
        Ok(buf.freeze())
      };

      let read_result: Result<Bytes, tonic::Status> = read_result_closure.await;

      let maybe_bytes = match read_result {
        Ok(bytes) => Some(bytes),
        Err(status) => {
          if status.code() == tonic::Code::NotFound {
            None
          } else {
            return Err(format!(
              "Error from server in response to CAS read request: {:?}",
              status
            ));
          }
        }
      };

      match maybe_bytes {
        Some(b) => f(b).map(Some),
        None => Ok(None),
      }
    };

    if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
      with_workunit(
        workunit_store_handle.store,
        workunit_name,
        metadata,
        result_future,
        |_, md| md,
      )
      .await
    } else {
      result_future.await
    }
  }

  ///
  /// Given a collection of Digests (digests),
  /// returns the set of digests from that collection not present in the CAS.
  ///
  pub fn list_missing_digests(
    &self,
    request: remexec::FindMissingBlobsRequest,
  ) -> impl Future<Output = Result<HashSet<Digest>, String>> {
    let store = self.clone();
    let workunit_name = format!(
      "list_missing_digests({})",
      store.instance_name.clone().unwrap_or_default()
    );
    let metadata = workunit_store::WorkunitMetadata::with_level(Level::Debug);
    let result_future = async move {
      let store2 = store.clone();
      let mut client = store2.cas_client.as_ref().clone();
      let request = request.clone();
      let response = client
        .find_missing_blobs(request)
        .map_err(|err| {
          format!(
            "Error from server in response to find_missing_blobs_request: {:?}",
            err
          )
        })
        .await?;

      response
        .into_inner()
        .missing_blob_digests
        .iter()
        .map(|digest| digest.try_into())
        .collect::<Result<HashSet<_>, _>>()
    };
    async {
      if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
        with_workunit(
          workunit_store_handle.store,
          workunit_name,
          metadata,
          result_future,
          |_, md| md,
        )
        .await
      } else {
        result_future.await
      }
    }
  }

  pub(super) fn find_missing_blobs_request<'a, Digests: Iterator<Item = &'a Digest>>(
    &self,
    digests: Digests,
  ) -> remexec::FindMissingBlobsRequest {
    remexec::FindMissingBlobsRequest {
      instance_name: self.instance_name.as_ref().cloned().unwrap_or_default(),
      blob_digests: digests.map(|d| d.into()).collect::<Vec<_>>(),
    }
  }
}
