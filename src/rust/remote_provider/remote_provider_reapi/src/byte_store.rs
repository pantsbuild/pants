// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{HashMap, HashSet};
use std::convert::TryInto;
use std::fmt;
use std::io::Cursor;
use std::sync::Arc;
use std::time::Instant;

use async_oncecell::OnceCell;
use async_trait::async_trait;
use bytes::Bytes;
use futures::{FutureExt, StreamExt};
use grpc_util::retry::{retry_call, status_is_retryable};
use grpc_util::{
    LayeredService, headers_to_http_header_map, layered_service, status_ref_to_str, status_to_str,
};
use hashing::{Digest, Hasher};
use protos::pb::build::bazel::remote::execution::v2 as remexec;
use protos::pb::google::bytestream::byte_stream_client::ByteStreamClient;
use remexec::{
    BatchUpdateBlobsRequest, ServerCapabilities, capabilities_client::CapabilitiesClient,
    content_addressable_storage_client::ContentAddressableStorageClient,
};
use tokio::fs::File;
use tokio::io::{AsyncRead, AsyncSeekExt, AsyncWriteExt};
use tokio::sync::Mutex;
use tonic::{Code, Request, Status};
use workunit_store::{Metric, ObservationMetric};

use remote_provider_traits::{
    BatchLoadDestination, ByteStoreProvider, LoadDestination, RemoteStoreOptions,
};

const RPC_DIGEST_SIZE: usize = 78;
const RPC_RESPONSE_PER_ITEM_SIZE: usize = 88;
const DEFAULT_MAX_GRPC_MESSAGE_SIZE: usize = 4 * 1024 * 1024;

pub struct Provider {
    instance_name: Option<String>,
    chunk_size_bytes: usize,
    _rpc_attempts: usize,
    byte_stream_client: Arc<ByteStreamClient<LayeredService>>,
    cas_client: Arc<ContentAddressableStorageClient<LayeredService>>,
    capabilities_cell: Arc<OnceCell<ServerCapabilities>>,
    capabilities_client: Arc<CapabilitiesClient<LayeredService>>,
    batch_api_size_limit: usize,
    batch_load_enabled: bool,
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
    fn is_retryable(&self) -> bool {
        match self {
            ByteStoreError::Grpc(status) => status_is_retryable(status),
            ByteStoreError::Other(_) => false,
        }
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

impl Provider {
    // TODO: Consider extracting these options to a struct with `impl Default`, similar to
    // `super::LocalOptions`.
    pub async fn new(options: RemoteStoreOptions) -> Result<Provider, String> {
        let tls_client_config = options
            .store_address
            .starts_with("https://")
            .then(|| options.tls_config.try_into())
            .transpose()?;

        let channel =
            grpc_util::create_channel(&options.store_address, tls_client_config.as_ref()).await?;
        let http_headers = headers_to_http_header_map(&options.headers)?;
        let channel = layered_service(
            channel,
            options.concurrency_limit,
            http_headers,
            Some((options.timeout, Metric::RemoteStoreRequestTimeouts)),
        );

        let byte_stream_client = Arc::new(ByteStreamClient::new(channel.clone()));

        let cas_client = Arc::new(ContentAddressableStorageClient::new(channel.clone()));

        let capabilities_client = Arc::new(CapabilitiesClient::new(channel));

        Ok(Provider {
            instance_name: options.instance_name,
            chunk_size_bytes: options.chunk_size_bytes,
            _rpc_attempts: options.retries + 1,
            byte_stream_client,
            cas_client,
            capabilities_cell: Arc::new(OnceCell::new()),
            capabilities_client,
            batch_api_size_limit: options.batch_api_size_limit,
            batch_load_enabled: options.batch_load_enabled,
        })
    }

    async fn store_bytes_batch(&self, digest: Digest, bytes: Bytes) -> Result<(), ByteStoreError> {
        let request = BatchUpdateBlobsRequest {
            instance_name: self.instance_name.clone().unwrap_or_default(),
            requests: vec![remexec::batch_update_blobs_request::Request {
                digest: Some(digest.into()),
                data: bytes,
                compressor: remexec::compressor::Value::Identity as i32,
            }],
            ..Default::default()
        };

        let mut client = self.cas_client.as_ref().clone();
        client
            .batch_update_blobs(request)
            .await
            .map_err(ByteStoreError::Grpc)?;
        Ok(())
    }

    async fn store_source_stream(
        &self,
        digest: Digest,
        source: Arc<Mutex<dyn AsyncRead + Send + Sync + Unpin + 'static>>,
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

        // we have to communicate the (first) error reading the underlying reader out of band
        let error_occurred = Arc::new(parking_lot::Mutex::new(None));
        let error_occurred_stream = error_occurred.clone();

        let chunk_size_bytes = self.chunk_size_bytes;
        let stream = async_stream::stream! {
          if len == 0 {
            // if the reader is empty, the ReaderStream gives no elements, but we have to write at least
            // one.
            yield protos::pb::google::bytestream::WriteRequest {
              resource_name: resource_name.clone(),
              write_offset: 0,
              finish_write: true,
              data: Bytes::new(),
            };
            return;
          }

          // Read the source in appropriately sized chunks.
          // NB. it is possible that this doesn't fill each chunk fully (i.e. may not send
          // `chunk_size_bytes` in each request). For the usual sources, this should be unlikely.
          let mut source = source.lock().await;
          let reader_stream = tokio_util::io::ReaderStream::with_capacity(&mut *source, chunk_size_bytes);
          let mut num_seen_bytes = 0;

          for await read_result in reader_stream {
            match read_result {
              Ok(data) => {
                let write_offset = num_seen_bytes as i64;
                num_seen_bytes += data.len();
                yield protos::pb::google::bytestream::WriteRequest {
                  resource_name: resource_name.clone(),
                  write_offset,
                  finish_write: num_seen_bytes == len,
                  data,
                }
              },
              Err(err) => {
                // reading locally hit an error, so store it for re-processing below
                *error_occurred_stream.lock() = Some(err);
                // cut off here, no point continuing
                break;
              }
            }
          }
        };

        // NB: We must box the future to avoid a stack overflow.
        // Explicit type annotation is a workaround for https://github.com/rust-lang/rust/issues/64552
        let future: std::pin::Pin<
            Box<dyn futures::Future<Output = Result<(), ByteStoreError>> + Send>,
        > = Box::pin(client.write(Request::new(stream)).map(move |r| {
            if let Some(ref read_err) = *error_occurred.lock() {
                // check if reading `source` locally hit an error: if so, propagate that error (there will
                // likely be a remote error too, because our write will be too short, but the local error is
                // the interesting root cause)
                return Err(ByteStoreError::Other(format!(
                    "Uploading file with digest {digest:?}: failed to read local source: {read_err}"
                )));
            }

            match r {
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
            }
        }));
        future.await
    }

    async fn get_capabilities(&self) -> Result<&remexec::ServerCapabilities, ByteStoreError> {
        let capabilities_fut = async {
            let mut request = remexec::GetCapabilitiesRequest::default();
            if let Some(s) = self.instance_name.as_ref() {
                request.instance_name.clone_from(s);
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

    fn validate_batch_response(
        digests: Vec<Digest>,
        response: remexec::BatchReadBlobsResponse,
    ) -> Result<HashMap<Digest, Result<Bytes, Status>>, String> {
        let mut results = HashMap::with_capacity(digests.len());

        for digest in digests {
            results.insert(
                digest,
                Err(Status::not_found("Digest not found in response")),
            );
        }

        for r in response.responses {
            if let Some(digest) = r.digest {
                let digest = digest.try_into().unwrap();

                if !results.contains_key(&digest) {
                    return Err(format!(
                        "Batch read returned unexpected digest {digest:?} in batch response"
                    ));
                }

                let status = r.status.map_or_else(
                    || Status::unknown("unknown error"),
                    |s| Status::new(Code::from_i32(s.code), s.message),
                );

                if status.code() == Code::Ok {
                    let mut hasher = Hasher::new();
                    hasher.update(&r.data);
                    let actual_digest = hasher.finish();

                    if actual_digest == digest {
                        results.insert(digest, Ok(r.data));
                    } else {
                        results.insert(digest, Err(Status::unknown(format!("Remote CAS gave wrong digest: expected {digest:?}, got {actual_digest:?}"))));
                    }
                } else {
                    results.insert(digest, Err(status));
                }
            }
        }

        Ok(results)
    }
}

#[async_trait]
impl ByteStoreProvider for Provider {
    async fn store_bytes(&self, digest: Digest, bytes: Bytes) -> Result<(), String> {
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
            move |bytes, _| async move {
                if batch_api_allowed_by_local_config && batch_api_allowed_by_server_config {
                    self.store_bytes_batch(digest, bytes).await
                } else {
                    self.store_source_stream(digest, Arc::new(Mutex::new(Cursor::new(bytes))))
                        .await
                }
            },
            ByteStoreError::is_retryable,
        )
        .await
        .map_err(|e| e.to_string())
    }

    async fn store_file(&self, digest: Digest, file: File) -> Result<(), String> {
        let source = Arc::new(Mutex::new(file));
        retry_call(
      source,
      move |source, retry_attempt| async move {
        if retry_attempt > 0 {
          // if we're retrying, we need to go back to the start of the source to start the whole
          // read fresh
          source.lock().await.rewind().await.map_err(|err| {
            ByteStoreError::Other(format!(
              "Uploading file with digest {digest:?}: failed to rewind before retry {retry_attempt}: {err}"
            ))
          })?;
        }

        // A file might be small enough to write via the batch API, but we ignore that possibility
        // for now, because these are expected to stored in the FSDB, and thus large
        self.store_source_stream(digest, source).await
      },
      ByteStoreError::is_retryable,
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

        let request = protos::pb::google::bytestream::ReadRequest {
            resource_name,
            read_offset: 0,
            // 0 means no limit.
            read_limit: 0,
        };
        let client = self.byte_stream_client.as_ref().clone();

        let destination = Arc::new(Mutex::new(destination));

        retry_call(
            (client, request, destination),
            move |(mut client, request, destination), retry_attempt| {
                async move {
                    let mut start_opt = Some(Instant::now());
                    let response = client.read(request).await?;

                    let mut stream = response.into_inner().inspect(|_| {
                        // Record the observed time to receive the first response for this read.
                        if let Some(start) = start_opt.take() {
                            let timing: Result<u64, _> =
                                Instant::now().duration_since(start).as_micros().try_into();

                            if let Ok(obs) = timing {
                                workunit_store::record_observation_if_in_workunit(
                                    ObservationMetric::RemoteStoreTimeToFirstByteMicros,
                                    obs,
                                );
                            }
                        }
                    });

                    let mut writer = destination.lock().await;
                    let mut hasher = Hasher::new();
                    if retry_attempt > 0 {
                        // if we're retrying, we need to clear out the destination to start the whole write
                        // fresh
                        writer.reset().await?;
                    }
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

    fn batch_load_supported(&self) -> bool {
        self.batch_load_enabled
    }

    async fn load_batch(
        &self,
        digests: Vec<Digest>,
        destination: &mut dyn BatchLoadDestination,
    ) -> Result<HashMap<Digest, Result<bool, String>>, String> {
        let mut max_batch_total_size_bytes = {
            let capabilities = self.get_capabilities().await.map_err(|e| e.to_string())?;

            capabilities
                .cache_capabilities
                .as_ref()
                .map(|c| c.max_batch_total_size_bytes as usize)
                .unwrap_or_default()
        };
        if max_batch_total_size_bytes == 0 || self.batch_api_size_limit < max_batch_total_size_bytes
        {
            max_batch_total_size_bytes = self.batch_api_size_limit;
        }
        if max_batch_total_size_bytes == 0 {
            max_batch_total_size_bytes = DEFAULT_MAX_GRPC_MESSAGE_SIZE;
        }
        max_batch_total_size_bytes = max_batch_total_size_bytes
            - self
                .instance_name
                .as_ref()
                .cloned()
                .unwrap_or_default()
                .len()
            - 10;

        let mut chunks: Vec<Vec<Digest>> = Vec::new();
        let mut current_chunk: Vec<Digest> = Vec::new();
        let mut current_size = 0;

        for digest in digests.iter() {
            let message_size = digest.size_bytes + RPC_RESPONSE_PER_ITEM_SIZE;
            if current_size + message_size >= max_batch_total_size_bytes {
                chunks.push(std::mem::take(&mut current_chunk));
                current_size = 0;
            }
            current_chunk.push(*digest);
            current_size += message_size;
        }

        if !current_chunk.is_empty() {
            chunks.push(current_chunk);
        }

        let client = self.cas_client.as_ref();
        let destination = Arc::new(Mutex::new(destination));

        let chunk_futures = chunks
            .clone()
            .into_iter()
            .map(|chunk| {
                let digests = chunk
                    .iter()
                    .map(|d| d.into())
                    .collect::<Vec<remexec::Digest>>();
                let request = remexec::BatchReadBlobsRequest {
                    instance_name: self.instance_name.as_ref().cloned().unwrap_or_default(),
                    digests: digests,
                    acceptable_compressors: vec![],
                    ..Default::default()
                };

                let client = client.clone();
                let destination = destination.clone();

                retry_call(
                    client,
                    move |mut client, _| {
                        let request = request.clone();
                        let chunk = chunk.clone();
                        let destination = destination.clone();

                        async move {
                            let response = client.batch_read_blobs(request).await?;
                            let responses =
                                Provider::validate_batch_response(chunk, response.into_inner())
                                    .map_err(Status::unknown)?;

                            if let Some(err) = responses.values().find_map(|res| res.as_ref().err())
                            {
                                return Err(err.clone());
                            }

                            let to_write = responses
                                .into_iter()
                                .map(|(d, res)| (d, res.unwrap()))
                                .collect::<Vec<_>>();

                            let digests = to_write.iter().map(|(d, _)| *d).collect::<Vec<_>>();

                            destination
                                .lock()
                                .await
                                .write(to_write)
                                .await
                                .map_err(Status::unknown)?;

                            Ok(digests)
                        }
                    },
                    status_is_retryable,
                )
            })
            .collect::<Vec<_>>();

        let chunk_results = futures::future::join_all(chunk_futures).await;

        let mut result = HashMap::new();

        for (response, digests) in chunk_results.into_iter().zip(chunks) {
            match response {
                Ok(digests) => {
                    for digest in digests {
                        result.insert(digest, Ok(true));
                    }
                }
                Err(err) => {
                    for digest in digests {
                        result.insert(digest, Err(err.to_string()));
                    }
                }
            }
        }
        Ok(result)
    }

    async fn list_missing_digests(
        &self,
        digests: &mut (dyn Iterator<Item = Digest> + Send),
    ) -> Result<HashSet<Digest>, String> {
        let blob_digests = digests.into_iter().map(|d| d.into()).collect::<Vec<_>>();

        const DEFAULT_MAX_GRPC_MESSAGE_SIZE: usize = 4 * 1024 * 1024;
        let max_digests_per_request: usize = (DEFAULT_MAX_GRPC_MESSAGE_SIZE
            - self
                .instance_name
                .as_ref()
                .cloned()
                .unwrap_or_default()
                .len()
            - 10)
            / RPC_DIGEST_SIZE;

        let requests = blob_digests.chunks(max_digests_per_request).map(|digests| {
            remexec::FindMissingBlobsRequest {
                instance_name: self.instance_name.as_ref().cloned().unwrap_or_default(),
                blob_digests: digests.to_vec(),
                ..Default::default()
            }
        });

        let client = self.cas_client.as_ref();
        let futures = requests
            .map(|request| {
                workunit_store::increment_counter_if_in_workunit(
                    Metric::RemoteStoreExistsAttempts,
                    1,
                );

                let client = client.clone();
                retry_call(
                    client,
                    move |mut client, _| {
                        let request = request.clone();
                        async move { client.find_missing_blobs(request).await }
                    },
                    status_is_retryable,
                )
            })
            .collect::<Vec<_>>();

        let result = futures::future::join_all(futures)
            .await
            .into_iter()
            .collect::<Result<Vec<_>, _>>()
            .map_err(status_to_str);

        let metric = match result {
            Ok(_) => Metric::RemoteStoreExistsSuccesses,
            Err(_) => Metric::RemoteStoreExistsErrors,
        };
        workunit_store::increment_counter_if_in_workunit(metric, 1);

        let response = result?;

        response
            .into_iter()
            .flat_map(|response| {
                response
                    .into_inner()
                    .missing_blob_digests
                    .into_iter()
                    .map(|digest| digest.try_into())
            })
            .collect::<Result<HashSet<_>, _>>()
    }
}

#[cfg(test)]
mod tests {

    use super::RPC_DIGEST_SIZE;
    use super::RPC_RESPONSE_PER_ITEM_SIZE;
    use crate::remexec::FindMissingBlobsRequest;
    use prost::Message;
    use protos::pb::build::bazel::remote::execution::v2;
    use protos::pb::google::rpc;
    use testutil::data::TestData;

    #[test]
    fn test_variable_size_of_blobs_request() {
        let instance_name = "";

        let small_request = FindMissingBlobsRequest {
            instance_name: instance_name.to_string(),
            blob_digests: vec![TestData::catnip().digest().into()],
            ..Default::default()
        };
        assert_eq!(small_request.encoded_len(), 70);

        let medium_request = FindMissingBlobsRequest {
            instance_name: instance_name.to_string(),
            blob_digests: vec![TestData::all_the_henries().digest().into()],
            ..Default::default()
        };
        assert_eq!(medium_request.encoded_len(), 72);

        let input_data = "a".repeat(400000000);
        let big_blob = TestData::new(&input_data).digest();

        let large_request = FindMissingBlobsRequest {
            instance_name: instance_name.to_string(),
            blob_digests: vec![big_blob.into()],
            ..Default::default()
        };
        assert_eq!(large_request.encoded_len(), 74);

        let max_request = FindMissingBlobsRequest {
            instance_name: instance_name.to_string(),
            blob_digests: vec![v2::Digest {
                hash: big_blob.hash.to_string(),
                size_bytes: i64::MAX,
            }],
            ..Default::default()
        };
        assert_eq!(max_request.encoded_len(), 78);
    }

    #[test]
    fn test_variable_size_of_batch_read_blobs_response() {
        fn ok(digest: v2::Digest, data: bytes::Bytes) -> v2::batch_read_blobs_response::Response {
            v2::batch_read_blobs_response::Response {
                digest: Some(digest),
                data,
                status: Some(rpc::Status {
                    code: rpc::Code::Ok as i32,
                    message: "".to_string(),
                    details: vec![],
                }),
                compressor: v2::compressor::Value::Identity as i32,
            }
        }

        let catnip = v2::Digest {
            hash: TestData::catnip().digest().hash.to_string(),
            size_bytes: TestData::catnip().digest().size_bytes as i64,
        };

        let small_request = v2::BatchReadBlobsResponse {
            responses: vec![ok(catnip.clone(), TestData::catnip().bytes())],
        };
        assert_eq!(small_request.encoded_len() as i64 - catnip.size_bytes, 76);

        let two_small_request = v2::BatchReadBlobsResponse {
            responses: vec![
                ok(catnip.clone(), TestData::catnip().bytes()),
                ok(catnip.clone(), TestData::catnip().bytes()),
            ],
        };
        assert_eq!(
            two_small_request.encoded_len() as i64 - catnip.size_bytes * 2,
            76 * 2
        );

        let all_the_henries = v2::Digest {
            hash: TestData::all_the_henries().digest().hash.to_string(),
            size_bytes: TestData::all_the_henries().digest().size_bytes as i64,
        };
        let medium_request = v2::BatchReadBlobsResponse {
            responses: vec![ok(
                all_the_henries.clone(),
                TestData::all_the_henries().bytes(),
            )],
        };
        assert_eq!(
            medium_request.encoded_len() as i64 - all_the_henries.size_bytes,
            82
        );

        let two_medium_request = v2::BatchReadBlobsResponse {
            responses: vec![
                ok(all_the_henries.clone(), TestData::all_the_henries().bytes()),
                ok(all_the_henries.clone(), TestData::all_the_henries().bytes()),
            ],
        };
        assert_eq!(
            two_medium_request.encoded_len() as i64 - all_the_henries.size_bytes * 2,
            82 * 2
        );

        let input_data = "a".repeat(i32::MAX as usize);
        let big_blob = TestData::new(&input_data).digest();

        let large_blob = v2::Digest {
            hash: big_blob.hash.to_string(),
            size_bytes: input_data.len() as i64,
        };
        let large_request = v2::BatchReadBlobsResponse {
            responses: vec![ok(large_blob.clone(), TestData::new(&input_data).bytes())],
        };
        assert_eq!(
            large_request.encoded_len() as i64 - large_blob.size_bytes,
            RPC_RESPONSE_PER_ITEM_SIZE as i64
        );
    }

    #[test]
    fn test_size_of_find_missing_blobs_request() {
        let mut blobs = Vec::new();
        let instance_name = "";
        // NOTE[TSolberg]: This test is a bit of a hack, but it's the best way I could think of to
        // ensure that the size of the FindMissingBlobsRequest is roughly what we expect. The only
        // delta would be the encoding of the instance name.
        for it in (0..10).chain(1000..1010).chain(10000..10010) {
            while blobs.len() < it {
                blobs.push(TestData::roland().digest().into());
            }

            let request = FindMissingBlobsRequest {
                instance_name: instance_name.to_string(),
                blob_digests: blobs.clone(),
                ..Default::default()
            };

            let size = request.encoded_len();

            // The test digests have a short lengths, so the length encoded size is smaller than the max
            assert_eq!(size, (RPC_DIGEST_SIZE - 8) * it);
        }
    }
}
