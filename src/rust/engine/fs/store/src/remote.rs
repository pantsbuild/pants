use super::{BackoffConfig, EntryType};

use bazel_protos::{self, call_option};
use boxfuture::{try_future, Boxable};
use bytes::{Bytes, BytesMut};
use concrete_time::TimeSpan;
use digest::{Digest as DigestTrait, FixedOutput};
use futures::compat::Future01CompatExt;
use futures01::{future, Future, IntoFuture, Sink, Stream};
use grpcio;
use hashing::{Digest, Fingerprint};
use serverset::{Retry, Serverset};
use sha2::Sha256;
use std::cmp::min;
use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;
use std::time::Duration;
use uuid;
use workunit_store::WorkUnit;

#[derive(Clone)]
pub struct ByteStore {
  instance_name: Option<String>,
  chunk_size_bytes: usize,
  upload_timeout: Duration,
  rpc_attempts: usize,
  env: Arc<grpcio::Environment>,
  serverset: Serverset<grpcio::Channel>,
  headers: BTreeMap<String, String>,
}

impl ByteStore {
  pub fn new(
    cas_addresses: Vec<String>,
    instance_name: Option<String>,
    root_ca_certs: Option<Vec<u8>>,
    oauth_bearer_token: Option<String>,
    thread_count: usize,
    chunk_size_bytes: usize,
    upload_timeout: Duration,
    backoff_config: BackoffConfig,
    rpc_retries: usize,
    connection_limit: usize,
  ) -> Result<ByteStore, String> {
    let env = Arc::new(grpcio::Environment::new(thread_count));
    let env2 = env.clone();

    let connect = move |cas_address: &str| {
      let builder = grpcio::ChannelBuilder::new(env2.clone());
      if let Some(ref root_ca_certs) = root_ca_certs {
        let creds = grpcio::ChannelCredentialsBuilder::new()
          .root_cert(root_ca_certs.clone())
          .build();
        builder.secure_connect(cas_address, creds)
      } else {
        builder.connect(cas_address)
      }
    };

    let serverset = Serverset::new(cas_addresses, connect, connection_limit, backoff_config)?;

    Ok(ByteStore {
      instance_name,
      chunk_size_bytes,
      upload_timeout,
      rpc_attempts: rpc_retries + 1,
      env,
      serverset,
      headers: oauth_bearer_token
        .iter()
        .map(|t| (String::from("authorization"), format!("Bearer {}", t)))
        .collect(),
    })
  }

  fn with_byte_stream_client<
    Value: Send + 'static,
    Fut: Future<Item = Value, Error = String>,
    IntoFut: IntoFuture<Future = Fut, Item = Value, Error = String>,
    F: Fn(bazel_protos::bytestream_grpc::ByteStreamClient) -> IntoFut + Send + Sync + Clone + 'static,
  >(
    &self,
    f: F,
  ) -> impl Future<Item = Value, Error = String> {
    Retry(self.serverset.clone()).all_errors_immediately(
      move |channel| {
        f(bazel_protos::bytestream_grpc::ByteStreamClient::new(
          channel,
        ))
      },
      self.rpc_attempts,
    )
  }

  fn with_cas_client<
    Value: Send + 'static,
    Fut: Future<Item = Value, Error = String>,
    IntoFut: IntoFuture<Future = Fut, Item = Value, Error = String>,
    F: Fn(bazel_protos::remote_execution_grpc::ContentAddressableStorageClient) -> IntoFut
      + Send
      + Sync
      + Clone
      + 'static,
  >(
    &self,
    f: F,
  ) -> impl Future<Item = Value, Error = String> {
    Retry(self.serverset.clone()).all_errors_immediately(
      move |channel| {
        f(bazel_protos::remote_execution_grpc::ContentAddressableStorageClient::new(channel))
      },
      self.rpc_attempts,
    )
  }

  pub async fn store_bytes(&self, bytes: Bytes) -> Result<Digest, String> {
    let start_time = std::time::SystemTime::now();

    let mut hasher = Sha256::default();
    hasher.input(&bytes);
    let fingerprint = Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice());
    let len = bytes.len();
    let digest = Digest(fingerprint, len);
    let resource_name = format!(
      "{}/uploads/{}/blobs/{}/{}",
      self.instance_name.clone().unwrap_or_default(),
      uuid::Uuid::new_v4(),
      digest.0,
      digest.1,
    );
    let workunit_name = format!("store_bytes({})", resource_name.clone());
    let store = self.clone();

    let result =
      self
        .with_byte_stream_client(move |client| {
          match client
            .write_opt(try_future!(call_option(&store.headers, None)).timeout(store.upload_timeout))
            .map(|v| (v, client))
          {
            Err(err) => future::err(format!(
              "Error attempting to connect to upload digest {:?}: {:?}",
              digest, err
            ))
            .to_boxed(),
            Ok(((sender, receiver), _client)) => {
              let chunk_size_bytes = store.chunk_size_bytes;
              let resource_name = resource_name.clone();
              let bytes = bytes.clone();
              let stream =
                futures01::stream::unfold::<_, _, future::FutureResult<_, grpcio::Error>, _>(
                  (0, false),
                  move |(offset, has_sent_any)| {
                    if offset >= bytes.len() && has_sent_any {
                      None
                    } else {
                      let mut req = bazel_protos::bytestream::WriteRequest::new();
                      req.set_resource_name(resource_name.clone());
                      req.set_write_offset(offset as i64);
                      let next_offset = min(offset + chunk_size_bytes, bytes.len());
                      req.set_finish_write(next_offset == bytes.len());
                      req.set_data(bytes.slice(offset, next_offset));
                      Some(future::ok((
                        (req, grpcio::WriteFlags::default()),
                        (next_offset, true),
                      )))
                    }
                  },
                );

              sender
                .send_all(stream)
                .map(|_| ())
                .or_else(move |e| {
                  match e {
                    // Some implementations of the remote execution API early-return if the blob has
                    // been concurrently uploaded by another client. In this case, they return a
                    // WriteResponse with a committed_size equal to the digest's entire size before
                    // closing the stream.
                    // Because the server then closes the stream, the client gets an RpcFinished
                    // error in this case. We ignore this, and will later on verify that the
                    // committed_size we received from the server is equal to the expected one. If
                    // these are not equal, the upload will be considered a failure at that point.
                    // Whether this type of response will become part of the official API is up for
                    // discussion: see
                    // https://groups.google.com/d/topic/remote-execution-apis/NXUe3ItCw68/discussion.
                    grpcio::Error::RpcFinished(None) => Ok(()),
                    e => Err(format!(
                      "Error attempting to upload digest {:?}: {:?}",
                      digest, e
                    )),
                  }
                })
                .and_then(move |()| {
                  receiver.map_err(move |e| {
                    format!(
                      "Error from server when uploading digest {:?}: {:?}",
                      digest, e
                    )
                  })
                })
                .and_then(move |received| {
                  if received.get_committed_size() == len as i64 {
                    Ok(digest)
                  } else {
                    Err(format!(
                      "Uploading file with digest {:?}: want commited size {} but got {}",
                      digest,
                      len,
                      received.get_committed_size()
                    ))
                  }
                })
                .to_boxed()
            }
          }
        })
        .compat()
        .await;

    if let Some(workunit_state) = workunit_store::get_workunit_state() {
      let workunit = WorkUnit::new(
        workunit_name.clone(),
        TimeSpan::since(&start_time),
        workunit_state.parent_id,
      );
      workunit_state.store.add_workunit(workunit);
    }

    result
  }

  pub async fn load_bytes_with<
    T: Send + 'static,
    F: Fn(Bytes) -> T + Send + Sync + Clone + 'static,
  >(
    &self,
    _entry_type: EntryType,
    digest: Digest,
    f: F,
  ) -> Result<Option<T>, String> {
    let start_time = std::time::SystemTime::now();

    let store = self.clone();
    let resource_name = format!(
      "{}/blobs/{}/{}",
      store.instance_name.clone().unwrap_or_default(),
      digest.0,
      digest.1
    );
    let workunit_name = format!("load_bytes_with({})", resource_name.clone());

    let result = self
      .with_byte_stream_client(move |client| {
        match client
          .read_opt(
            &{
              let mut req = bazel_protos::bytestream::ReadRequest::new();
              req.set_resource_name(resource_name.clone());
              req.set_read_offset(0);
              // 0 means no limit.
              req.set_read_limit(0);
              req
            },
            try_future!(call_option(&store.headers, None)),
          )
          .map(|stream| (stream, client))
        {
          Ok((stream, client)) => {
            let f = f.clone();
            // We shouldn't have to pass around the client here, it's a workaround for
            // https://github.com/pingcap/grpc-rs/issues/123
            future::ok(client)
              .join(
                stream.fold(BytesMut::with_capacity(digest.1), move |mut bytes, r| {
                  bytes.extend_from_slice(&r.data);
                  future::ok::<_, grpcio::Error>(bytes)
                }),
              )
              .map(|(_client, bytes)| Some(bytes.freeze()))
              .or_else(|e| match e {
                grpcio::Error::RpcFailure(grpcio::RpcStatus {
                  status: grpcio::RpcStatusCode::NOT_FOUND,
                  ..
                }) => Ok(None),
                _ => Err(format!(
                  "Error from server in response to CAS read request: {:?}",
                  e
                )),
              })
              .map(move |maybe_bytes| maybe_bytes.map(f))
              .to_boxed()
          }
          Err(err) => future::err(format!(
            "Error making CAS read request for {:?}: {:?}",
            digest, err
          ))
          .to_boxed(),
        }
      })
      .compat()
      .await;

    if let Some(workunit_state) = workunit_store::get_workunit_state() {
      let workunit = WorkUnit::new(
        workunit_name.clone(),
        TimeSpan::since(&start_time),
        workunit_state.parent_id,
      );
      workunit_state.store.add_workunit(workunit);
    }

    result
  }

  ///
  /// Given a collection of Digests (digests),
  /// returns the set of digests from that collection not present in the CAS.
  ///
  pub fn list_missing_digests(
    &self,
    request: bazel_protos::remote_execution::FindMissingBlobsRequest,
  ) -> impl Future<Item = HashSet<Digest>, Error = String> {
    let start_time = std::time::SystemTime::now();

    let store = self.clone();
    let workunit_name = format!(
      "list_missing_digests({})",
      store.instance_name.clone().unwrap_or_default()
    );
    self
      .with_cas_client(move |client| {
        client
          .find_missing_blobs_opt(&request, call_option(&store.headers, None)?)
          .map_err(|err| {
            format!(
              "Error from server in response to find_missing_blobs_request: {:?}",
              err
            )
          })
          .and_then(|response| {
            response
              .get_missing_blob_digests()
              .iter()
              .map(|digest| digest.into())
              .collect()
          })
      })
      .then(move |future| {
        if let Some(workunit_state) = workunit_store::get_workunit_state() {
          let workunit = WorkUnit::new(
            workunit_name.clone(),
            TimeSpan::since(&start_time),
            workunit_state.parent_id,
          );
          workunit_state.store.add_workunit(workunit);
        }
        future
      })
  }

  pub(super) fn find_missing_blobs_request<'a, Digests: Iterator<Item = &'a Digest>>(
    &self,
    digests: Digests,
  ) -> bazel_protos::remote_execution::FindMissingBlobsRequest {
    let mut request = bazel_protos::remote_execution::FindMissingBlobsRequest::new();
    if let Some(ref instance_name) = self.instance_name {
      request.set_instance_name(instance_name.clone());
    }
    for digest in digests {
      request.mut_blob_digests().push(digest.into());
    }
    request
  }
}
