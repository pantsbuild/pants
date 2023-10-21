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
use bytes::Bytes;
use futures::StreamExt;
use futures::{Future, FutureExt};
use grpc_util::retry::{retry_call, status_is_retryable};
use grpc_util::{
    headers_to_http_header_map, layered_service, status_ref_to_str, status_to_str, LayeredService,
};
use hashing::{Digest, Hasher};
use log::Level;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::google::bytestream::byte_stream_client::ByteStreamClient;
use remexec::{
    capabilities_client::CapabilitiesClient,
    content_addressable_storage_client::ContentAddressableStorageClient, BatchUpdateBlobsRequest,
    ServerCapabilities,
};
use tokio::io::{AsyncSeekExt, AsyncWrite, AsyncWriteExt};
use tokio::sync::Mutex;
use tonic::{Code, Request, Status};
use workunit_store::{in_workunit, Metric, ObservationMetric};

use crate::StoreError;

#[derive(Clone)]
pub struct ByteStore {
    instance_name: Option<String>,
    chunk_size_bytes: usize,
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
enum ByteStoreError {
    /// gRPC error
    Grpc(Status),

    /// Other errors
    Other(String),
}

impl ByteStoreError {
    fn retryable(&self) -> bool {
        match self {
            ByteStoreError::Grpc(status) => status_is_retryable(status),
            ByteStoreError::Other(_) => false,
        }
    }
}

impl From<Status> for ByteStoreError {
    fn from(status: Status) -> ByteStoreError {
        ByteStoreError::Grpc(status)
    }
}

impl From<String> for ByteStoreError {
    fn from(string: String) -> ByteStoreError {
        ByteStoreError::Other(string)
    }
}
impl From<std::io::Error> for ByteStoreError {
    fn from(err: std::io::Error) -> ByteStoreError {
        ByteStoreError::Other(err.to_string())
    }
}

impl fmt::Display for ByteStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ByteStoreError::Grpc(status) => fmt::Display::fmt(&status_ref_to_str(status), f),
            ByteStoreError::Other(msg) => fmt::Display::fmt(msg, f),
        }
    }
}

impl std::error::Error for ByteStoreError {}

/// Places that write the result of a remote `load`
#[async_trait]
trait LoadDestination: AsyncWrite + Send + Sync + Unpin + 'static {
    /// Clear out the writer and start again, if there's been previous contents written
    async fn reset(&mut self) -> std::io::Result<()>;
}

#[async_trait]
impl LoadDestination for tokio::fs::File {
    async fn reset(&mut self) -> std::io::Result<()> {
        self.rewind().await?;
        self.set_len(0).await
    }
}

#[async_trait]
impl LoadDestination for Vec<u8> {
    async fn reset(&mut self) -> std::io::Result<()> {
        self.clear();
        Ok(())
    }
}

impl ByteStore {
    // TODO: Consider extracting these options to a struct with `impl Default`, similar to
    // `super::LocalOptions`.
    pub fn new(
        cas_address: &str,
        instance_name: Option<String>,
        tls_config: grpc_util::tls::Config,
        mut headers: BTreeMap<String, String>,
        chunk_size_bytes: usize,
        rpc_timeout: Duration,
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
            Some((rpc_timeout, Metric::RemoteStoreRequestTimeouts)),
        );

        let byte_stream_client = Arc::new(ByteStreamClient::new(channel.clone()));

        let cas_client = Arc::new(ContentAddressableStorageClient::new(channel.clone()));

        let capabilities_client = Arc::new(CapabilitiesClient::new(channel));

        Ok(ByteStore {
            instance_name,
            chunk_size_bytes,
            _rpc_attempts: rpc_retries + 1,
            byte_stream_client,
            cas_client,
            capabilities_cell: capabilities_cell_opt.unwrap_or_else(|| Arc::new(OnceCell::new())),
            capabilities_client,
            batch_api_size_limit,
        })
    }

    pub(crate) fn chunk_size_bytes(&self) -> usize {
        self.chunk_size_bytes
    }

    pub async fn store_buffered<WriteToBuffer, WriteResult>(
        &self,
        digest: Digest,
        mut write_to_buffer: WriteToBuffer,
    ) -> Result<(), StoreError>
    where
        WriteToBuffer: FnMut(std::fs::File) -> WriteResult,
        WriteResult: Future<Output = Result<(), StoreError>>,
    {
        let write_buffer = tempfile::tempfile().map_err(|e| {
            format!("Failed to create a temporary blob upload buffer for {digest:?}: {e}")
        })?;
        let read_buffer = write_buffer.try_clone().map_err(|e| {
      format!("Failed to create a read handle for the temporary upload buffer for {digest:?}: {e}")
    })?;
        write_to_buffer(write_buffer).await?;

        // Unsafety: Mmap presents an immutable slice of bytes, but the underlying file that is mapped
        // could be mutated by another process. We guard against this by creating an anonymous
        // temporary file and ensuring it is written to and closed via the only other handle to it in
        // the code just above.
        let mmap = Arc::new(unsafe {
            let mapping = memmap::Mmap::map(&read_buffer).map_err(|e| {
                format!("Failed to memory map the temporary file buffer for {digest:?}: {e}")
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
            |mmap| {
                self.store_bytes_source(digest, move |range| Bytes::copy_from_slice(&mmap[range]))
            },
            ByteStoreError::retryable,
        )
        .await
        .map_err(|e| e.to_string().into())
    }

    pub async fn store_bytes(&self, bytes: Bytes) -> Result<(), String> {
        let digest = Digest::of_bytes(&bytes);
        retry_call(
            bytes,
            |bytes| self.store_bytes_source(digest, move |range| bytes.slice(range)),
            ByteStoreError::retryable,
        )
        .await
        .map_err(|e| e.to_string())
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

        let max_batch_total_size_bytes = {
            let capabilities = self.get_capabilities().await?;

            capabilities
                .cache_capabilities
                .as_ref()
                .map(|c| c.max_batch_total_size_bytes as usize)
                .unwrap_or_default()
        };

        let batch_api_allowed_by_local_config = len <= self.batch_api_size_limit;
        let batch_api_allowed_by_server_config =
            max_batch_total_size_bytes == 0 || len < max_batch_total_size_bytes;

        in_workunit!(
            "store_bytes",
            Level::Trace,
            desc = Some(format!("Storing {digest:?}")),
            |workunit| async move {
                let result =
                    if batch_api_allowed_by_local_config && batch_api_allowed_by_server_config {
                        self.store_bytes_source_batch(digest, bytes).await
                    } else {
                        self.store_bytes_source_stream(digest, bytes).await
                    };

                if result.is_ok() {
                    workunit.record_observation(
                        ObservationMetric::RemoteStoreBlobBytesUploaded,
                        len as u64,
                    );
                }

                result
            }
        )
        .await
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
        })
        .await
    }

    async fn load_monomorphic(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String> {
        let start = Instant::now();
        let store = self.clone();
        let instance_name = store.instance_name.clone().unwrap_or_default();
        let resource_name = format!(
            "{}{}blobs/{}/{}",
            &instance_name,
            if instance_name.is_empty() { "" } else { "/" },
            digest.hash,
            digest.size_bytes
        );
        let workunit_desc = format!("Loading bytes at: {resource_name}");

        let request = protos::gen::google::bytestream::ReadRequest {
            resource_name,
            read_offset: 0,
            // 0 means no limit.
            read_limit: 0,
        };
        let client = self.byte_stream_client.as_ref().clone();

        let destination = Arc::new(Mutex::new(destination));

        let result_future = retry_call(
            (client, request, destination),
            move |(mut client, request, destination)| {
                async move {
                    let mut start_opt = Some(Instant::now());
                    let response = client.read(request).await?;

                    let mut stream = response.into_inner().inspect(|_| {
                        // Record the observed time to receive the first response for this read.
                        if let Some(start) = start_opt.take() {
                            if let Some(workunit_store_handle) =
                                workunit_store::get_workunit_store_handle()
                            {
                                let timing: Result<u64, _> =
                                    Instant::now().duration_since(start).as_micros().try_into();
                                if let Ok(obs) = timing {
                                    workunit_store_handle.store.record_observation(
                                        ObservationMetric::RemoteStoreTimeToFirstByteMicros,
                                        obs,
                                    );
                                }
                            }
                        }
                    });

                    let mut writer = destination.lock().await;
                    let mut hasher = Hasher::new();
                    writer.reset().await?;
                    while let Some(response) = stream.next().await {
                        let response = response?;
                        writer.write_all(&response.data).await?;
                        hasher.update(&response.data);
                    }
                    writer.shutdown().await?;

                    let actual_digest = hasher.finish();
                    if actual_digest != digest {
                        // Return an `internal` status to attempt retry.
                        return Err(ByteStoreError::Grpc(Status::internal(format!(
              "Remote CAS gave wrong digest: expected {digest:?}, got {actual_digest:?}"
            ))));
                    }

                    Ok(())
                }
                .map(|read_result| match read_result {
                    Ok(()) => Ok(true),
                    Err(ByteStoreError::Grpc(status)) if status.code() == Code::NotFound => {
                        Ok(false)
                    }
                    Err(err) => Err(err),
                })
            },
            ByteStoreError::retryable,
        );

        in_workunit!(
            "load",
            Level::Trace,
            desc = Some(workunit_desc),
            |workunit| async move {
                let result = result_future.await.map_err(|e| e.to_string());
                workunit.record_observation(
                    ObservationMetric::RemoteStoreReadBlobTimeMicros,
                    start.elapsed().as_micros() as u64,
                );
                if result.is_ok() {
                    workunit.record_observation(
                        ObservationMetric::RemoteStoreBlobBytesDownloaded,
                        digest.size_bytes as u64,
                    );
                }
                result
            },
        )
        .await
    }

    async fn load<W: LoadDestination>(
        &self,
        digest: Digest,
        mut destination: W,
    ) -> Result<Option<W>, String> {
        if self.load_monomorphic(digest, &mut destination).await? {
            Ok(Some(destination))
        } else {
            Ok(None)
        }
    }

    /// Load the data for `digest` (if it exists in the remote store) into memory.
    pub async fn load_bytes(&self, digest: Digest) -> Result<Option<Bytes>, String> {
        let result = self
            .load(digest, Vec::with_capacity(digest.size_bytes))
            .await?;
        Ok(result.map(Bytes::from))
    }

    /// Write the data for `digest` (if it exists in the remote store) into `file`.
    pub async fn load_file(
        &self,
        digest: Digest,
        file: tokio::fs::File,
    ) -> Result<Option<tokio::fs::File>, String> {
        self.load(digest, file).await
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
        async {
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
                    .map_err(status_to_str)?;

                    response
                        .into_inner()
                        .missing_blob_digests
                        .iter()
                        .map(|digest| digest.try_into())
                        .collect::<Result<HashSet<_>, _>>()
                }
            )
            .await
        }
    }

    pub fn find_missing_blobs_request(
        &self,
        digests: impl IntoIterator<Item = Digest>,
    ) -> remexec::FindMissingBlobsRequest {
        remexec::FindMissingBlobsRequest {
            instance_name: self.instance_name.as_ref().cloned().unwrap_or_default(),
            blob_digests: digests.into_iter().map(|d| d.into()).collect::<Vec<_>>(),
        }
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

        self.capabilities_cell
            .get_or_try_init(capabilities_fut)
            .await
    }
}
