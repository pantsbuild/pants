// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::cmp::min;
use std::collections::HashSet;
use std::convert::TryInto;
use std::fmt;
use std::sync::Arc;
use std::time::Instant;

use async_oncecell::OnceCell;
use async_trait::async_trait;
use futures::{FutureExt, StreamExt};
use grpc_util::retry::{retry_call, status_is_retryable};
use grpc_util::{
    headers_to_http_header_map, layered_service, status_ref_to_str, status_to_str, LayeredService,
};
use hashing::{Digest, Hasher};
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::gen::google::bytestream::byte_stream_client::ByteStreamClient;
use remexec::{
    capabilities_client::CapabilitiesClient,
    content_addressable_storage_client::ContentAddressableStorageClient, BatchUpdateBlobsRequest,
    ServerCapabilities,
};
use tokio::io::AsyncWriteExt;
use tokio::sync::Mutex;
use tonic::{Code, Request, Status};
use workunit_store::{Metric, ObservationMetric};

use crate::RemoteOptions;

use super::{ByteSource, ByteStoreProvider, LoadDestination};

pub struct Provider {
    instance_name: Option<String>,
    chunk_size_bytes: usize,
    _rpc_attempts: usize,
    byte_stream_client: Arc<ByteStreamClient<LayeredService>>,
    cas_client: Arc<ContentAddressableStorageClient<LayeredService>>,
    capabilities_cell: Arc<OnceCell<ServerCapabilities>>,
    capabilities_client: Arc<CapabilitiesClient<LayeredService>>,
    batch_api_size_limit: usize,
}

/// Represents an error from accessing a remote bytestore.
#[derive(Debug)]
enum ByteStoreError {
    /// gRPC error
    Grpc(Status),

    /// Other errors
    Other(String),
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

impl Provider {
    // TODO: Consider extracting these options to a struct with `impl Default`, similar to
    // `super::LocalOptions`.
    pub async fn new(options: RemoteOptions) -> Result<Provider, String> {
        let tls_client_config = if options.cas_address.starts_with("https://") {
            Some(options.tls_config.try_into()?)
        } else {
            None
        };

        let channel =
            grpc_util::create_channel(&options.cas_address, tls_client_config.as_ref()).await?;
        let http_headers = headers_to_http_header_map(&options.headers)?;
        let channel = layered_service(
            channel,
            options.rpc_concurrency_limit,
            http_headers,
            Some((options.rpc_timeout, Metric::RemoteStoreRequestTimeouts)),
        );

        let byte_stream_client = Arc::new(ByteStreamClient::new(channel.clone()));

        let cas_client = Arc::new(ContentAddressableStorageClient::new(channel.clone()));

        let capabilities_client = Arc::new(CapabilitiesClient::new(channel));

        Ok(Provider {
            instance_name: options.instance_name,
            chunk_size_bytes: options.chunk_size_bytes,
            _rpc_attempts: options.rpc_retries + 1,
            byte_stream_client,
            cas_client,
            capabilities_cell: options
                .capabilities_cell_opt
                .unwrap_or_else(|| Arc::new(OnceCell::new())),
            capabilities_client,
            batch_api_size_limit: options.batch_api_size_limit,
        })
    }

    async fn store_bytes_source_batch(
        &self,
        digest: Digest,
        bytes: ByteSource,
    ) -> Result<(), ByteStoreError> {
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

    async fn store_bytes_source_stream(
        &self,
        digest: Digest,
        bytes: ByteSource,
    ) -> Result<(), ByteStoreError> {
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

        let mut client = self.byte_stream_client.as_ref().clone();

        let chunk_size_bytes = self.chunk_size_bytes;

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
        let future: std::pin::Pin<
            Box<dyn futures::Future<Output = Result<(), ByteStoreError>> + Send>,
        > = Box::pin(client.write(Request::new(stream)).map(|r| match r {
            Err(err) => Err(ByteStoreError::Grpc(err)),
            Ok(response) => {
                let response = response.into_inner();
                if response.committed_size == len as i64 {
                    Ok(())
                } else {
                    Err(ByteStoreError::Other(format!(
                        "Uploading file with digest {:?}: want committed size {} but got {}",
                        digest, len, response.committed_size
                    )))
                }
            }
        }));
        future.await
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

#[async_trait]
impl ByteStoreProvider for Provider {
    async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), String> {
        let len = digest.size_bytes;

        let max_batch_total_size_bytes = {
            let capabilities = self.get_capabilities().await.map_err(|e| e.to_string())?;

            capabilities
                .cache_capabilities
                .as_ref()
                .map(|c| c.max_batch_total_size_bytes as usize)
                .unwrap_or_default()
        };

        let batch_api_allowed_by_local_config = len <= self.batch_api_size_limit;
        let batch_api_allowed_by_server_config =
            max_batch_total_size_bytes == 0 || len < max_batch_total_size_bytes;

        retry_call(
            bytes,
            move |bytes| async move {
                if batch_api_allowed_by_local_config && batch_api_allowed_by_server_config {
                    self.store_bytes_source_batch(digest, bytes).await
                } else {
                    self.store_bytes_source_stream(digest, bytes).await
                }
            },
            |err| match err {
                ByteStoreError::Grpc(status) => status_is_retryable(status),
                ByteStoreError::Other(_) => false,
            },
        )
        .await
        .map_err(|e| e.to_string())
    }

    async fn load(
        &self,
        digest: Digest,
        destination: &mut dyn LoadDestination,
    ) -> Result<bool, String> {
        let instance_name = self.instance_name.clone().unwrap_or_default();
        let resource_name = format!(
            "{}{}blobs/{}/{}",
            &instance_name,
            if instance_name.is_empty() { "" } else { "/" },
            digest.hash,
            digest.size_bytes
        );

        let request = protos::gen::google::bytestream::ReadRequest {
            resource_name,
            read_offset: 0,
            // 0 means no limit.
            read_limit: 0,
        };
        let client = self.byte_stream_client.as_ref().clone();

        let destination = Arc::new(Mutex::new(destination));

        retry_call(
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
                        return Err(Status::internal(format!(
              "Remote CAS gave wrong digest: expected {digest:?}, got {actual_digest:?}"
            )));
                    }

                    Ok(())
                }
                .map(|read_result| match read_result {
                    Ok(()) => Ok(true),
                    Err(status) if status.code() == Code::NotFound => Ok(false),
                    Err(err) => Err(err),
                })
            },
            status_is_retryable,
        )
        .await
        .map_err(|e| e.to_string())
    }

    async fn list_missing_digests(
        &self,
        digests: &mut (dyn Iterator<Item = Digest> + Send),
    ) -> Result<HashSet<Digest>, String> {
        let request = remexec::FindMissingBlobsRequest {
            instance_name: self.instance_name.as_ref().cloned().unwrap_or_default(),
            blob_digests: digests.into_iter().map(|d| d.into()).collect::<Vec<_>>(),
        };

        let client = self.cas_client.as_ref().clone();
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

    fn chunk_size_bytes(&self) -> usize {
        self.chunk_size_bytes
    }
}
