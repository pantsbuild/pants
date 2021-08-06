use std::cmp::min;
use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::fmt;
use std::ops::Range;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::gen::google::bytestream::byte_stream_client::ByteStreamClient;
use bytes::{Bytes, BytesMut};
use double_checked_cell_async::DoubleCheckedCell;
use futures::Future;
use futures::StreamExt;
use grpc_util::retry::{retry_call, status_is_retryable};
use grpc_util::{headers_to_http_header_map, layered_service, status_to_str, LayeredService};
use hashing::Digest;
use log::Level;
use remexec::{
  capabilities_client::CapabilitiesClient,
  content_addressable_storage_client::ContentAddressableStorageClient, ServerCapabilities,
};
use tonic::{Code, Request, Status};
use workunit_store::{in_workunit, Metric, ObservationMetric, WorkunitMetadata};

#[derive(Clone)]
pub struct ByteStore {
  instance_name: Option<String>,
  chunk_size_bytes: usize,
  upload_timeout: Duration,
  rpc_attempts: usize,
  byte_stream_client: Arc<ByteStreamClient<LayeredService>>,
  cas_client: Arc<ContentAddressableStorageClient<LayeredService>>,
  capabilities_cell: Arc<DoubleCheckedCell<ServerCapabilities>>,
  capabilities_client: Arc<CapabilitiesClient<LayeredService>>,
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
      ByteStoreError::Grpc(status) => fmt::Display::fmt(status, f),
      ByteStoreError::Other(msg) => fmt::Display::fmt(msg, f),
    }
  }
}

impl std::error::Error for ByteStoreError {}

impl ByteStore {
  // TODO: Consider extracting these options to a struct with `impl Default`, similar to
  // `super::LocalOptions`.
  pub fn new(
    cas_address: &str,
    instance_name: Option<String>,
    root_ca_certs: Option<Vec<u8>>,
    mut headers: BTreeMap<String, String>,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    rpc_retries: usize,
    rpc_concurrency_limit: usize,
  ) -> Result<ByteStore, String> {
    let tls_client_config = if cas_address.starts_with("https://") {
      Some(grpc_util::create_tls_config(root_ca_certs)?)
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
    );

    let byte_stream_client = Arc::new(ByteStreamClient::new(channel.clone()));

    let cas_client = Arc::new(ContentAddressableStorageClient::new(channel.clone()));

    let capabilities_client = Arc::new(CapabilitiesClient::new(channel));

    Ok(ByteStore {
      instance_name,
      chunk_size_bytes,
      upload_timeout,
      rpc_attempts: rpc_retries + 1,
      byte_stream_client,
      cas_client,
      capabilities_cell: Arc::new(DoubleCheckedCell::new()),
      capabilities_client,
    })
  }

  pub(crate) fn chunk_size_bytes(&self) -> usize {
    self.chunk_size_bytes
  }

  pub async fn store_buffered<WriteToBuffer, WriteResult>(
    &self,
    digest: Digest,
    mut write_to_buffer: WriteToBuffer,
  ) -> Result<(), String>
  where
    WriteToBuffer: FnMut(std::fs::File) -> WriteResult,
    WriteResult: Future<Output = Result<(), String>>,
  {
    let write_buffer = tempfile::tempfile().map_err(|e| {
      format!(
        "Failed to create a temporary blob upload buffer for {digest:?}: {err}",
        digest = digest,
        err = e
      )
    })?;
    let read_buffer = write_buffer.try_clone().map_err(|e| {
      format!(
        "Failed to create a read handle for the temporary upload buffer for {digest:?}: {err}",
        digest = digest,
        err = e
      )
    })?;
    write_to_buffer(write_buffer).await?;

    // Unsafety: Mmap presents an immutable slice of bytes, but the underlying file that is mapped
    // could be mutated by another process. We guard against this by creating an anonymous
    // temporary file and ensuring it is written to and closed via the only other handle to it in
    // the code just above.
    let mmap = Arc::new(unsafe {
      let mapping = memmap::Mmap::map(&read_buffer).map_err(|e| {
        format!(
          "Failed to memory map the temporary file buffer for {digest:?}: {err}",
          digest = digest,
          err = e
        )
      })?;
      if let Err(err) = madvise::madvise(
        mapping.as_ptr(),
        mapping.len(),
        madvise::AccessPattern::Sequential,
      ) {
        log::warn!(
          "Failed to madvise(MADV_SEQUENTIAL) for the memory map of the temporary file buffer for \
          {digest:?}. Continuing with possible reduced performance: {err}",
          digest = digest,
          err = err
        )
      }
      Ok(mapping) as Result<memmap::Mmap, String>
    }?);

    retry_call(
      mmap,
      |mmap| self.store_bytes_source(digest, move |range| Bytes::copy_from_slice(&mmap[range])),
      |err| match err {
        ByteStoreError::Grpc(status) => status_is_retryable(status),
        _ => false,
      },
    )
    .await
    .map_err(|err| match err {
      ByteStoreError::Grpc(status) => status_to_str(status),
      ByteStoreError::Other(msg) => msg,
    })
  }

  pub async fn store_bytes(&self, bytes: Bytes) -> Result<(), String> {
    let digest = Digest::of_bytes(&bytes);
    retry_call(
      bytes,
      |bytes| self.store_bytes_source(digest, move |range| bytes.slice(range)),
      |err| match err {
        ByteStoreError::Grpc(status) => status_is_retryable(status),
        _ => false,
      },
    )
    .await
    .map_err(|err| match err {
      ByteStoreError::Grpc(status) => status_to_str(status),
      ByteStoreError::Other(msg) => msg,
    })
  }

  async fn store_bytes_source<ByteSource>(
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
    let workunit_name = format!("store_bytes({})", resource_name.clone());
    let workunit_metadata = WorkunitMetadata {
      level: Level::Debug,
      ..WorkunitMetadata::default()
    };
    let store = self.clone();

    let mut client = self.byte_stream_client.as_ref().clone();

    let resource_name = resource_name.clone();
    let chunk_size_bytes = store.chunk_size_bytes;

    let stream = futures::stream::unfold((0, false), move |(offset, has_sent_any)| {
      if offset >= len && has_sent_any {
        futures::future::ready(None)
      } else {
        let next_offset = min(offset + chunk_size_bytes, len);
        let req = bazel_protos::gen::google::bytestream::WriteRequest {
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
    let result_future = Box::pin(async move {
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

    if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
      let workunit_store = workunit_store_handle.store;
      in_workunit!(
        workunit_store,
        workunit_name,
        workunit_metadata,
        |workunit| async move {
          let result = result_future.await;
          if result.is_ok() {
            workunit.increment_counter(Metric::RemoteStoreBlobBytesUploaded, len as u64);
          }
          result
        },
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
  ) -> Result<Option<T>, ByteStoreError> {
    let store = self.clone();
    let instance_name = store.instance_name.clone().unwrap_or_default();
    let resource_name = format!(
      "{}{}blobs/{}/{}",
      &instance_name,
      if instance_name.is_empty() { "" } else { "/" },
      digest.hash,
      digest.size_bytes
    );
    let workunit_name = format!("load_bytes_with({})", resource_name.clone());
    let workunit_metadata = WorkunitMetadata {
      level: Level::Debug,
      ..WorkunitMetadata::default()
    };
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
        Err(status) => {
          return match status.code() {
            Code::NotFound => Ok(None),
            _ => Err(ByteStoreError::Grpc(status)),
          }
        }
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
            return Err(ByteStoreError::Grpc(status));
          }
        }
      };

      match maybe_bytes {
        Some(b) => f(b).map(Some).map_err(ByteStoreError::Other),
        None => Ok(None),
      }
    };

    if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
      in_workunit!(
        workunit_store_handle.store,
        workunit_name,
        workunit_metadata,
        |workunit| async move {
          let result = result_future.await;
          if result.is_ok() {
            workunit.increment_counter(
              Metric::RemoteStoreBlobBytesDownloaded,
              digest.size_bytes as u64,
            );
          }
          result
        },
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
    let workunit_metadata = WorkunitMetadata {
      level: Level::Debug,
      ..WorkunitMetadata::default()
    };
    let result_future = async move {
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
      .map_err(status_to_str)?;

      response
        .into_inner()
        .missing_blob_digests
        .iter()
        .map(|digest| digest.try_into())
        .collect::<Result<HashSet<_>, _>>()
    };
    async {
      if let Some(workunit_store_handle) = workunit_store::get_workunit_store_handle() {
        in_workunit!(
          workunit_store_handle.store,
          workunit_name,
          workunit_metadata,
          |_workunit| result_future,
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

  #[allow(dead_code)]
  async fn get_capabilities(&self) -> Result<&remexec::ServerCapabilities, String> {
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
        .map_err(status_to_str)
    };

    self
      .capabilities_cell
      .get_or_try_init(capabilities_fut)
      .await
  }
}
