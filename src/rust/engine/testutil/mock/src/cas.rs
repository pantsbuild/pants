use std::collections::HashMap;
use std::convert::TryInto;
use std::net::SocketAddr;
use std::sync::Arc;

use crate::tonic_util::AddrIncomingWithStream;
use bazel_protos::gen::build::bazel::remote::execution::v2 as remexec;
use bazel_protos::gen::build::bazel::semver::SemVer;
use bazel_protos::gen::google::bytestream::{
  byte_stream_server::ByteStream, byte_stream_server::ByteStreamServer, QueryWriteStatusRequest,
  QueryWriteStatusResponse, ReadRequest, ReadResponse, WriteRequest, WriteResponse,
};
use bytes::{Bytes, BytesMut};
use futures::stream::StreamExt;
use futures::{FutureExt, Stream};
use hashing::{Digest, Fingerprint};
use parking_lot::Mutex;
use remexec::capabilities_server::{Capabilities, CapabilitiesServer};
use remexec::content_addressable_storage_server::{
  ContentAddressableStorage, ContentAddressableStorageServer,
};
use remexec::{
  BatchReadBlobsRequest, BatchReadBlobsResponse, BatchUpdateBlobsRequest, BatchUpdateBlobsResponse,
  CacheCapabilities, ExecutionCapabilities, FindMissingBlobsRequest, FindMissingBlobsResponse,
  GetCapabilitiesRequest, GetTreeRequest, GetTreeResponse, ServerCapabilities,
};
use std::pin::Pin;
use testutil::data::{TestData, TestDirectory, TestTree};
use tonic::metadata::{AsciiMetadataKey, KeyAndValueRef};
use tonic::transport::Server;
use tonic::{Request, Response, Status};

///
/// Implements the ContentAddressableStorage gRPC API, answering read requests with either known
/// content, NotFound for valid but unknown content, or InvalidArguments for bad arguments.
///
pub struct StubCAS {
  read_request_count: Arc<Mutex<usize>>,
  pub write_message_sizes: Arc<Mutex<Vec<usize>>>,
  pub blobs: Arc<Mutex<HashMap<Fingerprint, Bytes>>>,
  local_addr: SocketAddr,
  shutdown_sender: Option<tokio::sync::oneshot::Sender<()>>,
}

impl Drop for StubCAS {
  fn drop(&mut self) {
    if let Some(s) = self.shutdown_sender.take() {
      let _ = s.send(());
    }
  }
}

pub struct StubCASBuilder {
  always_errors: bool,
  chunk_size_bytes: Option<usize>,
  content: HashMap<Fingerprint, Bytes>,
  port: Option<u16>,
  instance_name: Option<String>,
  required_auth_token: Option<String>,
}

impl StubCASBuilder {
  pub fn new() -> Self {
    StubCASBuilder {
      always_errors: false,
      chunk_size_bytes: None,
      content: HashMap::new(),
      port: None,
      instance_name: None,
      required_auth_token: None,
    }
  }
}

impl StubCASBuilder {
  pub fn chunk_size_bytes(mut self, chunk_size_bytes: usize) -> Self {
    if self.chunk_size_bytes.is_some() {
      panic!("Can't set chunk_size_bytes twice");
    }
    self.chunk_size_bytes = Some(chunk_size_bytes);
    self
  }

  pub fn port(mut self, port: u16) -> Self {
    if self.port.is_some() {
      panic!("Can't set port twice");
    }
    self.port = Some(port);
    self
  }

  pub fn file(mut self, file: &TestData) -> Self {
    self.content.insert(file.fingerprint(), file.bytes());
    self
  }

  pub fn directory(mut self, directory: &TestDirectory) -> Self {
    self
      .content
      .insert(directory.fingerprint(), directory.bytes());
    self
  }

  pub fn tree(mut self, tree: &TestTree) -> Self {
    self.content.insert(tree.fingerprint(), tree.bytes());
    self
  }

  pub fn unverified_content(mut self, fingerprint: Fingerprint, content: Bytes) -> Self {
    self.content.insert(fingerprint, content);
    self
  }

  pub fn always_errors(mut self) -> Self {
    self.always_errors = true;
    self
  }

  pub fn instance_name(mut self, instance_name: String) -> Self {
    if self.instance_name.is_some() {
      panic!("Can't set instance_name twice");
    }
    self.instance_name = Some(instance_name);
    self
  }

  pub fn required_auth_token(mut self, required_auth_token: String) -> Self {
    if self.required_auth_token.is_some() {
      panic!("Can't set required_auth_token twice");
    }
    self.required_auth_token = Some(required_auth_token);
    self
  }

  pub fn build(self) -> StubCAS {
    StubCAS::new(
      self.chunk_size_bytes.unwrap_or(1024),
      self.content,
      self.port.unwrap_or(0),
      self.always_errors,
      self.instance_name,
      self.required_auth_token,
    )
  }
}

impl StubCAS {
  pub fn builder() -> StubCASBuilder {
    StubCASBuilder::new()
  }

  ///
  /// # Arguments
  /// * `chunk_size_bytes` - The maximum number of bytes of content to include per streamed message.
  ///                        Messages will saturate until the last one, which may be smaller than
  ///                        this value.
  ///                        If a negative value is given, all requests will receive an error.
  /// * `blobs`            - Known Fingerprints and their content responses. These are not checked
  ///                        for correctness.
  /// * `port`             - The port for the CAS to listen to.
  fn new(
    chunk_size_bytes: usize,
    blobs: HashMap<Fingerprint, Bytes>,
    port: u16,
    always_errors: bool,
    instance_name: Option<String>,
    required_auth_token: Option<String>,
  ) -> StubCAS {
    let read_request_count = Arc::new(Mutex::new(0));
    let write_message_sizes = Arc::new(Mutex::new(Vec::new()));
    let blobs = Arc::new(Mutex::new(blobs));
    let responder = StubCASResponder {
      chunk_size_bytes,
      instance_name,
      blobs: blobs.clone(),
      always_errors,
      read_request_count: read_request_count.clone(),
      write_message_sizes: write_message_sizes.clone(),
      required_auth_header: required_auth_token.map(|t| format!("Bearer {}", t)),
    };

    let addr = format!("127.0.0.1:{}", port)
      .parse()
      .expect("failed to parse IP address");
    let incoming = hyper::server::conn::AddrIncoming::bind(&addr).expect("failed to bind port");
    let local_addr = incoming.local_addr();
    let incoming = AddrIncomingWithStream(incoming);

    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel();

    tokio::spawn(async move {
      let mut server = Server::builder();
      let router = server
        .add_service(ByteStreamServer::new(responder.clone()))
        .add_service(ContentAddressableStorageServer::new(responder.clone()))
        .add_service(CapabilitiesServer::new(responder));

      router
        .serve_with_incoming_shutdown(incoming, shutdown_receiver.map(drop))
        .await
        .unwrap();
    });

    StubCAS {
      read_request_count,
      write_message_sizes,
      blobs,
      local_addr,
      shutdown_sender: Some(shutdown_sender),
    }
  }

  pub fn empty() -> StubCAS {
    StubCAS::builder().build()
  }

  pub fn always_errors() -> StubCAS {
    StubCAS::builder().always_errors().build()
  }

  ///
  /// The address on which this server is listening over insecure HTTP transport.
  ///
  pub fn address(&self) -> String {
    format!("{}", self.local_addr)
  }

  pub fn read_request_count(&self) -> usize {
    *self.read_request_count.lock()
  }
}

#[derive(Clone, Debug)]
pub struct StubCASResponder {
  chunk_size_bytes: usize,
  instance_name: Option<String>,
  blobs: Arc<Mutex<HashMap<Fingerprint, Bytes>>>,
  always_errors: bool,
  required_auth_header: Option<String>,
  pub read_request_count: Arc<Mutex<usize>>,
  pub write_message_sizes: Arc<Mutex<Vec<usize>>>,
}

macro_rules! check_auth {
  ($self:ident, $req:ident) => {
    if let Some(ref required_auth_header) = $self.required_auth_header {
      let auth_header = AsciiMetadataKey::from_static("authorization");
      let authorization_headers: Vec<_> = $req
        .metadata()
        .iter()
        .filter_map(|kv| match kv {
          KeyAndValueRef::Ascii(key, value) if key == auth_header => Some((key, value)),
          _ => None,
        })
        .map(|(_key, value)| value)
        .collect();
      if authorization_headers.len() != 1
        || authorization_headers[0] != required_auth_header.as_bytes()
      {
        return Err(Status::unauthenticated(format!(
          "Bad Authorization header; want {:?} got {:?}",
          required_auth_header.as_bytes(),
          authorization_headers
        )));
      }
    }
  };
}

macro_rules! check_instance_name {
  ($self:ident, $req:ident) => {
    if $req.instance_name != $self.instance_name() {
      return Err(Status::not_found(format!(
        "Instance {} does not exist",
        $req.instance_name
      )));
    }
  };
}

impl StubCASResponder {
  fn instance_name(&self) -> String {
    self.instance_name.clone().unwrap_or_default()
  }

  fn read_internal(&self, req: &ReadRequest) -> Result<Vec<ReadResponse>, Status> {
    let parts: Vec<_> = req.resource_name.splitn(4, '/').collect();
    if parts.len() != 4
      || parts.get(0) != Some(&self.instance_name().as_ref())
      || parts.get(1) != Some(&"blobs")
    {
      return Err(Status::invalid_argument(format!(
        "Bad resource name format {} - want {}/blobs/some-sha256/size",
        req.resource_name,
        self.instance_name(),
      )));
    }
    let digest = parts[2];
    let fingerprint = Fingerprint::from_hex_string(digest)
      .map_err(|e| Status::invalid_argument(format!("Bad digest {}: {}", digest, e)))?;
    if self.always_errors {
      return Err(Status::internal(
        "StubCAS is configured to always fail".to_owned(),
      ));
    }
    let blobs = self.blobs.lock();
    let maybe_bytes = blobs.get(&fingerprint);
    match maybe_bytes {
      Some(bytes) => Ok(
        bytes
          .chunks(self.chunk_size_bytes as usize)
          .map(|b| ReadResponse {
            data: bytes.slice_ref(b),
          })
          .collect(),
      ),
      None => Err(Status::not_found(format!(
        "Did not find digest {}",
        fingerprint
      ))),
    }
  }
}

#[tonic::async_trait]
impl ByteStream for StubCASResponder {
  type ReadStream = Pin<Box<dyn Stream<Item = Result<ReadResponse, Status>> + Send + Sync>>;

  async fn read(
    &self,
    request: Request<ReadRequest>,
  ) -> Result<Response<Self::ReadStream>, Status> {
    {
      let mut request_count = self.read_request_count.lock();
      *request_count += 1;
    }
    check_auth!(self, request);

    let request = request.into_inner();

    let stream_elements = self.read_internal(&request)?;
    let stream = Box::pin(futures::stream::iter(
      stream_elements.into_iter().map(Ok).collect::<Vec<_>>(),
    ));
    Ok(Response::new(stream))
  }

  async fn write(
    &self,
    request: Request<tonic::Streaming<WriteRequest>>,
  ) -> Result<Response<WriteResponse>, Status> {
    check_auth!(self, request);

    let always_errors = self.always_errors;
    let write_message_sizes = self.write_message_sizes.clone();
    let blobs = self.blobs.clone();
    let instance_name = self.instance_name();

    let mut stream = request.into_inner();

    let mut maybe_resource_name = None;
    let mut want_next_offset = 0;
    let mut bytes = BytesMut::new();

    while let Some(req_result) = stream.next().await {
      let req = match req_result {
        Ok(r) => r,
        Err(e) => {
          return Err(Status::invalid_argument(format!(
            "Client sent an error: {}",
            e
          )))
        }
      };

      match maybe_resource_name {
        None => maybe_resource_name = Some(req.resource_name.clone()),
        Some(ref resource_name) => {
          if *resource_name != req.resource_name {
            return Err(Status::invalid_argument(format!(
              "All resource names in stream must be the same. Got {} but earlier saw {}",
              req.resource_name, resource_name
            )));
          }
        }
      }

      if req.write_offset != want_next_offset {
        return Err(Status::invalid_argument(format!(
          "Missing chunk. Expected next offset {}, got next offset: {}",
          want_next_offset, req.write_offset
        )));
      }

      want_next_offset += req.data.len() as i64;
      write_message_sizes.lock().push(req.data.len());
      bytes.extend_from_slice(&req.data);
    }

    let bytes = bytes.freeze();

    match maybe_resource_name {
      None => Err(Status::invalid_argument(
        "Stream saw no messages".to_owned(),
      )),
      Some(resource_name) => {
        let parts: Vec<_> = resource_name.splitn(6, '/').collect();
        if parts.len() != 6
          || parts.get(0) != Some(&instance_name.as_ref())
          || parts.get(1) != Some(&"uploads")
          || parts.get(3) != Some(&"blobs")
        {
          return Err(Status::invalid_argument(format!(
            "Bad resource name: {}",
            resource_name
          )));
        }
        let fingerprint = match Fingerprint::from_hex_string(parts[4]) {
          Ok(f) => f,
          Err(err) => {
            return Err(Status::invalid_argument(format!(
              "Bad fingerprint in resource name: {}: {}",
              parts[4], err
            )));
          }
        };
        let size = match parts[5].parse::<usize>() {
          Ok(s) => s,
          Err(err) => {
            return Err(Status::invalid_argument(format!(
              "Bad size in resource name: {}: {}",
              parts[5], err
            )));
          }
        };
        if size != bytes.len() {
          return Err(Status::invalid_argument(format!(
            "Size was incorrect: resource name said size={} but got {}",
            size,
            bytes.len()
          )));
        }

        if always_errors {
          return Err(Status::invalid_argument(
            "StubCAS is configured to always fail".to_owned(),
          ));
        }

        {
          let mut blobs = blobs.lock();
          blobs.insert(fingerprint, bytes);
        }

        let response = WriteResponse {
          committed_size: size as i64,
        };
        Ok(Response::new(response))
      }
    }
  }

  async fn query_write_status(
    &self,
    _: Request<QueryWriteStatusRequest>,
  ) -> Result<Response<QueryWriteStatusResponse>, Status> {
    Err(Status::unimplemented("".to_owned()))
  }
}

#[tonic::async_trait]
impl ContentAddressableStorage for StubCASResponder {
  async fn find_missing_blobs(
    &self,
    request: Request<FindMissingBlobsRequest>,
  ) -> Result<Response<FindMissingBlobsResponse>, Status> {
    check_auth!(self, request);

    if self.always_errors {
      return Err(Status::internal(
        "StubCAS is configured to always fail".to_owned(),
      ));
    }

    let request = request.into_inner();

    check_instance_name!(self, request);

    let blobs = self.blobs.lock();
    let mut response = FindMissingBlobsResponse::default();
    for digest in request.blob_digests {
      let hashing_digest_result: Result<Digest, String> = digest.try_into();
      let hashing_digest = hashing_digest_result.expect("Bad digest");
      if !blobs.contains_key(&hashing_digest.fingerprint) {
        response.missing_blob_digests.push(hashing_digest.into())
      }
    }
    Ok(Response::new(response))
  }

  async fn batch_update_blobs(
    &self,
    _: Request<BatchUpdateBlobsRequest>,
  ) -> Result<Response<BatchUpdateBlobsResponse>, Status> {
    Err(Status::unimplemented("".to_owned()))
  }

  async fn batch_read_blobs(
    &self,
    _: Request<BatchReadBlobsRequest>,
  ) -> Result<Response<BatchReadBlobsResponse>, Status> {
    Err(Status::unimplemented("".to_owned()))
  }

  type GetTreeStream = tonic::codec::Streaming<GetTreeResponse>;

  async fn get_tree(
    &self,
    _: Request<GetTreeRequest>,
  ) -> Result<Response<Self::GetTreeStream>, Status> {
    Err(Status::unimplemented("".to_owned()))
  }
}

#[tonic::async_trait]
impl Capabilities for StubCASResponder {
  async fn get_capabilities(
    &self,
    request: Request<GetCapabilitiesRequest>,
  ) -> Result<Response<ServerCapabilities>, Status> {
    let request = request.into_inner();
    check_instance_name!(self, request);

    let response = ServerCapabilities {
      cache_capabilities: Some(CacheCapabilities {
        digest_function: vec![remexec::digest_function::Value::Sha256 as i32],
        max_batch_total_size_bytes: 0,
        ..CacheCapabilities::default()
      }),
      execution_capabilities: Some(ExecutionCapabilities {
        digest_function: remexec::digest_function::Value::Sha256 as i32,
        exec_enabled: true,
        ..ExecutionCapabilities::default()
      }),
      high_api_version: Some(SemVer {
        major: 2,
        minor: 999,
        ..SemVer::default()
      }),
      ..ServerCapabilities::default()
    };

    Ok(Response::new(response))
  }
}
