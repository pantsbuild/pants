use std::cmp::min;
use std::collections::{BTreeMap, HashSet};
use std::convert::TryInto;
use std::fmt;
use std::ops::Range;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_oncecell::OnceCell;
use bytes::{Bytes, BytesMut};
use futures::Future;
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

use crate::StoreError;

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
            |mmap| {
                self.store_bytes_source(digest, move |range| Bytes::copy_from_slice(&mmap[range]))
            },
            |err| match err {
                ByteStoreError::Grpc(status) => status_is_retryable(status),
                _ => false,
            },
        )
        .await
        .map_err(|err| match err {
            ByteStoreError::Grpc(status) => status_to_str(status).into(),
            ByteStoreError::Other(msg) => msg.into(),
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

    pub async fn load_bytes_with<
        T: Send + 'static,
        F: Fn(Bytes) -> Result<T, String> + Send + Sync + Clone + 'static,
    >(
        &self,
        digest: Digest,
        f: F,
    ) -> Result<Option<T>, ByteStoreError> {
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
        let f = f.clone();

        let mut client = self.byte_stream_client.as_ref().clone();

        let result_future = async move {
            let mut start_opt = Some(Instant::now());

            let stream_result = client
                .read({
                    protos::gen::google::bytestream::ReadRequest {
                        resource_name,
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

        in_workunit!(
            "load_bytes_with",
            Level::Trace,
            desc = Some(workunit_desc),
            |workunit| async move {
                let result = result_future.await;
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
