use super::{BackoffConfig, EntryType};

use bazel_protos;
use boxfuture::{BoxFuture, Boxable};
use bytes::{Bytes, BytesMut};
use concrete_time::TimeSpan;
use digest::{Digest as DigestTrait, FixedOutput};
use futures::{self, future, Future, IntoFuture, Sink, Stream};
use grpcio;
use hashing::{Digest, Fingerprint};
use serverset::{Retry, Serverset};
use sha2::Sha256;
use std::cmp::min;
use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;
use uuid;
use workunit_store::WorkUnitStore;

#[derive(Clone)]
pub struct ByteStore {
  instance_name: Option<String>,
  chunk_size_bytes: usize,
  upload_timeout: Duration,
  rpc_attempts: usize,
  env: Arc<grpcio::Environment>,
  serverset: Serverset<grpcio::Channel>,
  authorization_header: Option<String>,
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
      authorization_header: oauth_bearer_token.map(|t| format!("Bearer {}", t)),
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

  fn call_option(&self) -> grpcio::CallOption {
    let mut call_option = grpcio::CallOption::default();
    if let Some(ref authorization_header) = self.authorization_header {
      let mut builder = grpcio::MetadataBuilder::with_capacity(1);
      builder
        .add_str("authorization", &authorization_header)
        .unwrap();
      call_option = call_option.headers(builder.build());
    }
    call_option
  }

  pub fn store_bytes(
    &self,
    bytes: Bytes,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Digest, String> {
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
    let workunit_store = workunit_store.clone();
    let store = self.clone();
    self
      .with_byte_stream_client(move |client| {
        match client
          .write_opt(store.call_option().timeout(store.upload_timeout))
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
              futures::stream::unfold::<_, _, futures::future::FutureResult<_, grpcio::Error>, _>(
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
      .then(move |future| {
        let workunit = workunit_store::WorkUnit {
          name: workunit_name.clone(),
          time_span: TimeSpan::since(&start_time),
          span_id: workunit_store::generate_random_64bit_string(),
          parent_id: workunit_store::get_parent_id(),
        };
        workunit_store.add_workunit(workunit);
        future
      })
      .to_boxed()
  }

  pub fn load_bytes_with<T: Send + 'static, F: Fn(Bytes) -> T + Send + Sync + Clone + 'static>(
    &self,
    _entry_type: EntryType,
    digest: Digest,
    f: F,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Option<T>, String> {
    let start_time = std::time::SystemTime::now();

    let store = self.clone();
    let resource_name = format!(
      "{}/blobs/{}/{}",
      store.instance_name.clone().unwrap_or_default(),
      digest.0,
      digest.1
    );
    let workunit_name = format!("load_bytes_with({})", resource_name.clone());
    let workunit_store = workunit_store.clone();
    self
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
            store.call_option(),
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
                  status: grpcio::RpcStatusCode::NotFound,
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
      .then(move |future| {
        let workunit = workunit_store::WorkUnit {
          name: workunit_name.clone(),
          time_span: TimeSpan::since(&start_time),
          span_id: workunit_store::generate_random_64bit_string(),
          parent_id: workunit_store::get_parent_id(),
        };
        workunit_store.add_workunit(workunit);
        future
      })
      .to_boxed()
  }

  ///
  /// Given a collection of Digests (digests),
  /// returns the set of digests from that collection not present in the CAS.
  ///
  pub fn list_missing_digests(
    &self,
    request: bazel_protos::remote_execution::FindMissingBlobsRequest,
    workunit_store: WorkUnitStore,
  ) -> impl Future<Item = HashSet<Digest>, Error = String> {
    let start_time = std::time::SystemTime::now();

    let store = self.clone();
    let workunit_name = format!(
      "list_missing_digests({})",
      store.instance_name.clone().unwrap_or_default()
    );
    let workunit_store = workunit_store.clone();
    self
      .with_cas_client(move |client| {
        client
          .find_missing_blobs_opt(&request, store.call_option())
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
        let workunit = workunit_store::WorkUnit {
          name: workunit_name.clone(),
          time_span: TimeSpan::since(&start_time),
          span_id: workunit_store::generate_random_64bit_string(),
          parent_id: workunit_store::get_parent_id(),
        };
        workunit_store.add_workunit(workunit);
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

#[cfg(test)]
mod tests {
  use super::super::{EntryType, MEGABYTES};
  use super::ByteStore;
  use bytes::Bytes;
  use hashing::Digest;
  use mock::StubCAS;
  use serverset::BackoffConfig;
  use std::collections::HashSet;
  use std::time::Duration;
  use testutil::data::{TestData, TestDirectory};
  use workunit_store::WorkUnitStore;

  use super::super::tests::{
    big_file_bytes, big_file_digest, big_file_fingerprint, block_on, new_cas,
  };

  #[test]
  fn loads_file() {
    let testdata = TestData::roland();
    let cas = new_cas(10);

    assert_eq!(
      load_file_bytes(&new_byte_store(&cas), testdata.digest()).unwrap(),
      Some(testdata.bytes())
    );
  }

  #[test]
  fn missing_file() {
    let cas = StubCAS::empty();

    assert_eq!(
      load_file_bytes(&new_byte_store(&cas), TestData::roland().digest()),
      Ok(None)
    );
  }

  #[test]
  fn load_directory() {
    let cas = new_cas(10);
    let testdir = TestDirectory::containing_roland();

    assert_eq!(
      load_directory_proto_bytes(&new_byte_store(&cas), testdir.digest()),
      Ok(Some(testdir.bytes()))
    );
  }

  #[test]
  fn missing_directory() {
    let cas = StubCAS::empty();

    assert_eq!(
      load_directory_proto_bytes(
        &new_byte_store(&cas),
        TestDirectory::containing_roland().digest()
      ),
      Ok(None)
    );
  }

  #[test]
  fn load_file_grpc_error() {
    let cas = StubCAS::always_errors();

    let error =
      load_file_bytes(&new_byte_store(&cas), TestData::roland().digest()).expect_err("Want error");
    assert!(
      error.contains("StubCAS is configured to always fail"),
      format!("Bad error message, got: {}", error)
    )
  }

  #[test]
  fn load_directory_grpc_error() {
    let cas = StubCAS::always_errors();

    let error = load_directory_proto_bytes(
      &new_byte_store(&cas),
      TestDirectory::containing_roland().digest(),
    )
    .expect_err("Want error");
    assert!(
      error.contains("StubCAS is configured to always fail"),
      format!("Bad error message, got: {}", error)
    )
  }

  #[test]
  fn fetch_less_than_one_chunk() {
    let testdata = TestData::roland();
    let cas = new_cas(testdata.bytes().len() + 1);

    assert_eq!(
      load_file_bytes(&new_byte_store(&cas), testdata.digest()),
      Ok(Some(testdata.bytes()))
    )
  }

  #[test]
  fn fetch_exactly_one_chunk() {
    let testdata = TestData::roland();
    let cas = new_cas(testdata.bytes().len());

    assert_eq!(
      load_file_bytes(&new_byte_store(&cas), testdata.digest()),
      Ok(Some(testdata.bytes()))
    )
  }

  #[test]
  fn fetch_multiple_chunks_exact() {
    let testdata = TestData::roland();
    let cas = new_cas(1);

    assert_eq!(
      load_file_bytes(&new_byte_store(&cas), testdata.digest()),
      Ok(Some(testdata.bytes()))
    )
  }

  #[test]
  fn fetch_multiple_chunks_nonfactor() {
    let testdata = TestData::roland();
    let cas = new_cas(9);

    assert_eq!(
      load_file_bytes(&new_byte_store(&cas), testdata.digest()),
      Ok(Some(testdata.bytes()))
    )
  }

  #[test]
  fn write_file_one_chunk() {
    let testdata = TestData::roland();
    let cas = StubCAS::empty();

    let store = new_byte_store(&cas);
    assert_eq!(
      block_on(store.store_bytes(testdata.bytes(), WorkUnitStore::new())),
      Ok(testdata.digest())
    );

    let blobs = cas.blobs.lock();
    assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
  }

  #[test]
  fn write_file_multiple_chunks() {
    let cas = StubCAS::empty();

    let store = ByteStore::new(
      vec![cas.address()],
      None,
      None,
      None,
      1,
      10 * 1024,
      Duration::from_secs(5),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
    )
    .unwrap();

    let all_the_henries = big_file_bytes();

    let fingerprint = big_file_fingerprint();

    assert_eq!(
      block_on(store.store_bytes(all_the_henries.clone(), WorkUnitStore::new())),
      Ok(big_file_digest())
    );

    let blobs = cas.blobs.lock();
    assert_eq!(blobs.get(&fingerprint), Some(&all_the_henries));

    let write_message_sizes = cas.write_message_sizes.lock();
    assert_eq!(
      write_message_sizes.len(),
      98,
      "Wrong number of chunks uploaded"
    );
    for size in write_message_sizes.iter() {
      assert!(
        size <= &(10 * 1024),
        format!("Size {} should have been <= {}", size, 10 * 1024)
      );
    }
  }

  #[test]
  fn write_empty_file() {
    let empty_file = TestData::empty();
    let cas = StubCAS::empty();

    let store = new_byte_store(&cas);
    assert_eq!(
      block_on(store.store_bytes(empty_file.bytes(), WorkUnitStore::new())),
      Ok(empty_file.digest())
    );

    let blobs = cas.blobs.lock();
    assert_eq!(
      blobs.get(&empty_file.fingerprint()),
      Some(&empty_file.bytes())
    );
  }

  #[test]
  fn write_file_errors() {
    let cas = StubCAS::always_errors();

    let store = new_byte_store(&cas);
    let error = block_on(store.store_bytes(TestData::roland().bytes(), WorkUnitStore::new()))
      .expect_err("Want error");
    assert!(
      error.contains("Error from server"),
      format!("Bad error message, got: {}", error)
    );
    assert!(
      error.contains("StubCAS is configured to always fail"),
      format!("Bad error message, got: {}", error)
    );
  }

  #[test]
  fn write_connection_error() {
    let store = ByteStore::new(
      vec![String::from("doesnotexist.example")],
      None,
      None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
    )
    .unwrap();
    let error = block_on(store.store_bytes(TestData::roland().bytes(), WorkUnitStore::new()))
      .expect_err("Want error");
    assert!(
      error.contains("Error attempting to upload digest"),
      format!("Bad error message, got: {}", error)
    );
  }

  #[test]
  fn list_missing_digests_none_missing() {
    let cas = new_cas(1024);

    let store = new_byte_store(&cas);
    assert_eq!(
      block_on(store.list_missing_digests(
        store.find_missing_blobs_request(vec![TestData::roland().digest()].iter()),
        WorkUnitStore::new(),
      )),
      Ok(HashSet::new())
    );
  }

  #[test]
  fn list_missing_digests_some_missing() {
    let cas = StubCAS::empty();

    let store = new_byte_store(&cas);

    let digest = TestData::roland().digest();

    let mut digest_set = HashSet::new();
    digest_set.insert(digest);

    assert_eq!(
      block_on(store.list_missing_digests(
        store.find_missing_blobs_request(vec![digest].iter()),
        WorkUnitStore::new(),
      )),
      Ok(digest_set)
    );
  }

  #[test]
  fn list_missing_digests_error() {
    let cas = StubCAS::always_errors();

    let store = new_byte_store(&cas);

    let error = block_on(store.list_missing_digests(
      store.find_missing_blobs_request(vec![TestData::roland().digest()].iter()),
      WorkUnitStore::new(),
    ))
    .expect_err("Want error");
    assert!(
      error.contains("StubCAS is configured to always fail"),
      format!("Bad error message, got: {}", error)
    );
  }

  #[test]
  fn reads_from_multiple_cas_servers() {
    let roland = TestData::roland();
    let catnip = TestData::catnip();

    let cas1 = StubCAS::builder().file(&roland).file(&catnip).build();
    let cas2 = StubCAS::builder().file(&roland).file(&catnip).build();

    let store = ByteStore::new(
      vec![cas1.address(), cas2.address()],
      None,
      None,
      None,
      1,
      10 * 1024 * 1024,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      2,
    )
    .unwrap();

    assert_eq!(
      load_file_bytes(&store, roland.digest()),
      Ok(Some(roland.bytes()))
    );

    assert_eq!(
      load_file_bytes(&store, catnip.digest()),
      Ok(Some(catnip.bytes()))
    );

    assert_eq!(cas1.read_request_count(), 1);
    assert_eq!(cas2.read_request_count(), 1);
  }

  fn new_byte_store(cas: &StubCAS) -> ByteStore {
    ByteStore::new(
      vec![cas.address()],
      None,
      None,
      None,
      1,
      10 * MEGABYTES,
      Duration::from_secs(1),
      BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
      1,
      1,
    )
    .unwrap()
  }

  pub fn load_file_bytes(store: &ByteStore, digest: Digest) -> Result<Option<Bytes>, String> {
    load_bytes(&store, EntryType::File, digest)
  }

  pub fn load_directory_proto_bytes(
    store: &ByteStore,
    digest: Digest,
  ) -> Result<Option<Bytes>, String> {
    load_bytes(&store, EntryType::Directory, digest)
  }

  fn load_bytes(
    store: &ByteStore,
    entry_type: EntryType,
    digest: Digest,
  ) -> Result<Option<Bytes>, String> {
    block_on(store.load_bytes_with(entry_type, digest, |b| b, WorkUnitStore::new()))
  }
}
