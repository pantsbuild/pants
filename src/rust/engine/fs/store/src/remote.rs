use std::cmp::min;
use std::collections::{BTreeMap, HashSet};
use std::convert::{TryFrom, TryInto};
use std::fmt;
use std::str::FromStr;
use std::time::Duration;

use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::gen::google::bytestream::byte_stream_client::ByteStreamClient;
use bazel_protos::{self};
use bytes::{Bytes, BytesMut};
use futures::future::{FutureExt, TryFutureExt};
use futures::StreamExt;
use futures01::Future;
use hashing::Digest;
use itertools::{Either, Itertools};
use log::Level;
use remexec::content_addressable_storage_client::ContentAddressableStorageClient;
use tokio_rustls::rustls::ClientConfig;
use tonic::transport::{Channel, ClientTlsConfig, Endpoint};
use tonic::{Code, Interceptor, Request};
use workunit_store::with_workunit;

use super::BackoffConfig;
use std::sync::Arc;
use tonic::metadata::{AsciiMetadataKey, AsciiMetadataValue, KeyAndValueRef, MetadataMap};

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
    oauth_bearer_token: Option<String>,
    _thread_count: usize,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    _backoff_config: BackoffConfig,
    rpc_retries: usize,
    _connection_limit: usize,
  ) -> Result<ByteStore, String> {
    let tls_client_config = match root_ca_certs {
      Some(pem_bytes) => {
        let mut tls_config = ClientConfig::new();
        let mut reader = std::io::Cursor::new(pem_bytes);
        tls_config
          .root_store
          .add_pem_file(&mut reader)
          .map_err(|_| "unexpected state in PEM file add".to_owned())?;
        Some(tls_config)
      }
      None => None,
    };

    let scheme = if tls_client_config.is_some() {
      "https"
    } else {
      "http"
    };

    let cas_addresses_with_scheme: Vec<_> = cas_addresses
      .iter()
      .map(|addr| format!("{}://{}", scheme, addr))
      .collect();

    let (endpoints, errors): (Vec<Endpoint>, Vec<String>) = cas_addresses_with_scheme
      .iter()
      .map(|addr| {
        let uri = tonic::transport::Uri::try_from(addr)
          .map_err(|err| format!("invalid address: {}", err))?;
        let endpoint = Channel::builder(uri);
        let maybe_tls_endpoint = if let Some(ref config) = tls_client_config {
          endpoint
            .tls_config(ClientTlsConfig::new().rustls_client_config(config.clone()))
            .map_err(|e| format!("TLS setup error: {}", e))?
        } else {
          endpoint
        };
        Ok(maybe_tls_endpoint)
      })
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

    let headers = oauth_bearer_token
      .iter()
      .map(|t| {
        (
          String::from("authorization"),
          format!("Bearer {}", t.trim()),
        )
      })
      .collect::<BTreeMap<_, _>>();

    let mut metadata = MetadataMap::with_capacity(headers.len());
    for (key, value) in &headers {
      let key_ascii = AsciiMetadataKey::from_str(key.as_str()).map_err(|_| {
        format!(
          "Header key `{}` must be an ASCII value (as required by gRPC).",
          key
        )
      })?;
      let value_ascii = AsciiMetadataValue::from_str(value.as_str()).map_err(|_| {
        format!(
          "Header value `{}` for key `{}` must be an ASCII value (as required by gRPC).",
          value, key
        )
      })?;
      metadata.insert(key_ascii, value_ascii);
    }

    let interceptor = if headers.is_empty() {
      None
    } else {
      Some(Interceptor::new(move |mut req: Request<()>| {
        let req_metadata = req.metadata_mut();
        for kv_ref in metadata.iter() {
          match kv_ref {
            KeyAndValueRef::Ascii(key, value) => {
              req_metadata.insert(key, value.clone());
            }
            KeyAndValueRef::Binary(key, value) => {
              req_metadata.insert_bin(key, value.clone());
            }
          }
        }
        Ok(req)
      }))
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
      digest.0,
      digest.1,
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
          data: Vec::from(&bytes[offset..next_offset]),
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

    if let Some(workunit_state) = workunit_store::get_workunit_state() {
      let store = workunit_state.store;
      with_workunit(store, workunit_name, metadata, result_future, |_, md| md).await
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
      digest.0,
      digest.1
    );
    let workunit_name = format!("load_bytes_with({})", resource_name.clone());
    let metadata = workunit_store::WorkunitMetadata::with_level(Level::Debug);
    let resource_name = resource_name.clone();
    let f = f.clone();

    let mut client = self.byte_stream_client.as_ref().clone();

    let result_future = async move {
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
        let mut buf = BytesMut::with_capacity(digest.1);
        while let Some(response) = stream.next().await {
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

    if let Some(workunit_state) = workunit_store::get_workunit_state() {
      let store = workunit_state.store;
      with_workunit(store, workunit_name, metadata, result_future, |_, md| md).await
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
  ) -> impl Future<Item = HashSet<Digest>, Error = String> {
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
      if let Some(workunit_state) = workunit_store::get_workunit_state() {
        let store = workunit_state.store;
        with_workunit(store, workunit_name, metadata, result_future, |_, md| md).await
      } else {
        result_future.await
      }
    }
    .boxed()
    .compat()
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
