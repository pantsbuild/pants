use std::collections::HashMap;
use std::convert::TryInto;
use std::sync::Arc;

use bytes::Bytes;
use futures01::{Future, IntoFuture, Stream};
use hashing::{Digest, Fingerprint};
use parking_lot::Mutex;
use testutil::data::{TestData, TestDirectory};

///
/// Implements the ContentAddressableStorage gRPC API, answering read requests with either known
/// content, NotFound for valid but unknown content, or InvalidArguments for bad arguments.
///
pub struct StubCAS {
  server_transport: grpcio::Server,
  read_request_count: Arc<Mutex<usize>>,
  pub write_message_sizes: Arc<Mutex<Vec<usize>>>,
  pub blobs: Arc<Mutex<HashMap<Fingerprint, Bytes>>>,
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
    let env = Arc::new(grpcio::Environment::new(1));
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
    let mut server_transport = grpcio::ServerBuilder::new(env)
      .register_service(bazel_protos::bytestream_grpc::create_byte_stream(
        responder.clone(),
      ))
      .register_service(
        bazel_protos::remote_execution_grpc::create_content_addressable_storage(responder),
      )
      .bind("localhost", port)
      .build()
      .unwrap();
    server_transport.start();

    StubCAS {
      server_transport,
      read_request_count,
      write_message_sizes,
      blobs,
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
    let bind_addr = self.server_transport.bind_addrs().next().unwrap();
    format!("{}:{}", bind_addr.0, bind_addr.1)
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
  ($self:ident, $ctx:ident, $sink:ident) => {
    if let Some(ref required_auth_header) = $self.required_auth_header {
      let authorization_headers: Vec<_> = $ctx
        .request_headers()
        .iter()
        .filter(|(key, _value)| &key.to_lowercase() == "authorization")
        .map(|(_key, value)| value)
        .collect();
      if authorization_headers.len() != 1
        || authorization_headers[0] != required_auth_header.as_bytes()
      {
        $ctx.spawn(
          $sink
            .fail(grpcio::RpcStatus::new(
              grpcio::RpcStatusCode::UNAUTHENTICATED,
              Some(format!(
                "Bad Authorization header; want {:?} got {:?}",
                required_auth_header.as_bytes(),
                authorization_headers
              )),
            ))
            .then(|_| Ok(())),
        );
        return;
      }
    }
  };
}

impl StubCASResponder {
  fn instance_name(&self) -> String {
    self.instance_name.clone().unwrap_or_default()
  }

  fn read_internal(
    &self,
    req: &bazel_protos::bytestream::ReadRequest,
  ) -> Result<Vec<bazel_protos::bytestream::ReadResponse>, grpcio::RpcStatus> {
    let parts: Vec<_> = req.get_resource_name().splitn(4, '/').collect();
    if parts.len() != 4
      || parts.get(0) != Some(&self.instance_name().as_ref())
      || parts.get(1) != Some(&"blobs")
    {
      return Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::INVALID_ARGUMENT,
        Some(format!(
          "Bad resource name format {} - want {}/blobs/some-sha256/size",
          req.get_resource_name(),
          self.instance_name(),
        )),
      ));
    }
    let digest = parts[2];
    let fingerprint = Fingerprint::from_hex_string(digest).map_err(|e| {
      grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::INVALID_ARGUMENT,
        Some(format!("Bad digest {}: {}", digest, e)),
      )
    })?;
    if self.always_errors {
      return Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::INTERNAL,
        Some("StubCAS is configured to always fail".to_owned()),
      ));
    }
    let blobs = self.blobs.lock();
    let maybe_bytes = blobs.get(&fingerprint);
    match maybe_bytes {
      Some(bytes) => Ok(
        bytes
          .chunks(self.chunk_size_bytes as usize)
          .map(|b| {
            let mut resp = bazel_protos::bytestream::ReadResponse::new();
            resp.set_data(Bytes::from(b));
            resp
          })
          .collect(),
      ),
      None => Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::NOT_FOUND,
        Some(format!("Did not find digest {}", fingerprint)),
      )),
    }
  }

  ///
  /// Sends a stream of responses down a sink, in ctx's threadpool.
  ///
  fn send<Item, S>(
    &self,
    ctx: &grpcio::RpcContext<'_>,
    sink: grpcio::ServerStreamingSink<Item>,
    stream: S,
  ) where
    Item: Send + 'static,
    S: Stream<Item = (Item, grpcio::WriteFlags), Error = grpcio::Error> + Send + 'static,
  {
    ctx.spawn(stream.forward(sink).map(|_| ()).map_err(|_| ()));
  }
}

impl bazel_protos::bytestream_grpc::ByteStream for StubCASResponder {
  fn read(
    &self,
    ctx: grpcio::RpcContext<'_>,
    req: bazel_protos::bytestream::ReadRequest,
    sink: grpcio::ServerStreamingSink<bazel_protos::bytestream::ReadResponse>,
  ) {
    {
      let mut request_count = self.read_request_count.lock();
      *request_count += 1;
    }
    check_auth!(self, ctx, sink);

    match self.read_internal(&req) {
      Ok(response) => self.send(
        &ctx,
        sink,
        futures01::stream::iter_ok(
          response
            .into_iter()
            .map(|chunk| (chunk, grpcio::WriteFlags::default())),
        ),
      ),
      Err(err) => {
        ctx.spawn(sink.fail(err).then(|_| Ok(())));
      }
    }
  }

  fn write(
    &self,
    ctx: grpcio::RpcContext<'_>,
    stream: grpcio::RequestStream<bazel_protos::bytestream::WriteRequest>,
    sink: grpcio::ClientStreamingSink<bazel_protos::bytestream::WriteResponse>,
  ) {
    check_auth!(self, ctx, sink);

    let always_errors = self.always_errors;
    let write_message_sizes = self.write_message_sizes.clone();
    let blobs = self.blobs.clone();
    let instance_name = self.instance_name();
    ctx.spawn(
      stream
        .collect()
        .into_future()
        .and_then(move |reqs| {
          let mut maybe_resource_name = None;
          let mut want_next_offset = 0;
          let mut bytes = Bytes::new();
          for req in reqs {
            match maybe_resource_name {
              None => maybe_resource_name = Some(req.get_resource_name().to_owned()),
              Some(ref resource_name) => {
                if resource_name != req.get_resource_name() {
                  return Err(grpcio::Error::RpcFailure(grpcio::RpcStatus::new(
                    grpcio::RpcStatusCode::INVALID_ARGUMENT,
                    Some(format!(
                      "All resource names in stream must be the same. Got {} but earlier saw {}",
                      req.get_resource_name(),
                      resource_name
                    )),
                  )));
                }
              }
            }
            if req.get_write_offset() != want_next_offset {
              return Err(grpcio::Error::RpcFailure(grpcio::RpcStatus::new(
                grpcio::RpcStatusCode::INVALID_ARGUMENT,
                Some(format!(
                  "Missing chunk. Expected next offset {}, got next offset: {}",
                  want_next_offset,
                  req.get_write_offset()
                )),
              )));
            }
            want_next_offset += req.get_data().len() as i64;
            write_message_sizes.lock().push(req.get_data().len());
            bytes.extend(req.get_data());
          }
          Ok((maybe_resource_name, bytes))
        })
        .map_err(move |err: grpcio::Error| match err {
          grpcio::Error::RpcFailure(status) => status,
          e => grpcio::RpcStatus::new(grpcio::RpcStatusCode::UNKNOWN, Some(format!("{:?}", e))),
        })
        .and_then(
          move |(maybe_resource_name, bytes)| match maybe_resource_name {
            None => Err(grpcio::RpcStatus::new(
              grpcio::RpcStatusCode::INVALID_ARGUMENT,
              Some("Stream saw no messages".to_owned()),
            )),
            Some(resource_name) => {
              let parts: Vec<_> = resource_name.splitn(6, '/').collect();
              if parts.len() != 6
                || parts.get(0) != Some(&instance_name.as_ref())
                || parts.get(1) != Some(&"uploads")
                || parts.get(3) != Some(&"blobs")
              {
                return Err(grpcio::RpcStatus::new(
                  grpcio::RpcStatusCode::INVALID_ARGUMENT,
                  Some(format!("Bad resource name: {}", resource_name)),
                ));
              }
              let fingerprint = match Fingerprint::from_hex_string(parts[4]) {
                Ok(f) => f,
                Err(err) => {
                  return Err(grpcio::RpcStatus::new(
                    grpcio::RpcStatusCode::INVALID_ARGUMENT,
                    Some(format!(
                      "Bad fingerprint in resource name: {}: {}",
                      parts[4], err
                    )),
                  ));
                }
              };
              let size = match parts[5].parse::<usize>() {
                Ok(s) => s,
                Err(err) => {
                  return Err(grpcio::RpcStatus::new(
                    grpcio::RpcStatusCode::INVALID_ARGUMENT,
                    Some(format!("Bad size in resource name: {}: {}", parts[5], err)),
                  ));
                }
              };
              if size != bytes.len() {
                return Err(grpcio::RpcStatus::new(
                  grpcio::RpcStatusCode::INVALID_ARGUMENT,
                  Some(format!(
                    "Size was incorrect: resource name said size={} but got {}",
                    size,
                    bytes.len()
                  )),
                ));
              }

              if always_errors {
                return Err(grpcio::RpcStatus::new(
                  grpcio::RpcStatusCode::INTERNAL,
                  Some("StubCAS is configured to always fail".to_owned()),
                ));
              }

              {
                let mut blobs = blobs.lock();
                blobs.insert(fingerprint, bytes);
              }

              let mut response = bazel_protos::bytestream::WriteResponse::new();
              response.set_committed_size(size as i64);
              Ok(response)
            }
          },
        )
        .then(move |result| match result {
          Ok(resp) => sink.success(resp),
          Err(err) => sink.fail(err),
        })
        .then(move |_| Ok(())),
    );
  }

  fn query_write_status(
    &self,
    _ctx: grpcio::RpcContext<'_>,
    _req: bazel_protos::bytestream::QueryWriteStatusRequest,
    sink: grpcio::UnarySink<bazel_protos::bytestream::QueryWriteStatusResponse>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::UNIMPLEMENTED,
      None,
    ));
  }
}

impl bazel_protos::remote_execution_grpc::ContentAddressableStorage for StubCASResponder {
  fn find_missing_blobs(
    &self,
    ctx: grpcio::RpcContext<'_>,
    req: bazel_protos::remote_execution::FindMissingBlobsRequest,
    sink: grpcio::UnarySink<bazel_protos::remote_execution::FindMissingBlobsResponse>,
  ) {
    check_auth!(self, ctx, sink);

    if self.always_errors {
      sink.fail(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::INTERNAL,
        Some("StubCAS is configured to always fail".to_owned()),
      ));
      return;
    }
    if req.instance_name != self.instance_name() {
      sink.fail(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::NOT_FOUND,
        Some(format!(
          "Wrong instance_name; want {:?} got {:?}",
          self.instance_name(),
          req.instance_name
        )),
      ));
      return;
    }
    let blobs = self.blobs.lock();
    let mut response = bazel_protos::remote_execution::FindMissingBlobsResponse::new();
    for digest in req.get_blob_digests() {
      let hashing_digest_result: Result<Digest, String> = digest.try_into();
      let hashing_digest = hashing_digest_result.expect("Bad digest");
      if !blobs.contains_key(&hashing_digest.0) {
        response.mut_missing_blob_digests().push(digest.clone())
      }
    }
    sink.success(response);
  }

  fn batch_update_blobs(
    &self,
    _ctx: grpcio::RpcContext<'_>,
    _req: bazel_protos::remote_execution::BatchUpdateBlobsRequest,
    sink: grpcio::UnarySink<bazel_protos::remote_execution::BatchUpdateBlobsResponse>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::UNIMPLEMENTED,
      None,
    ));
  }
  fn get_tree(
    &self,
    _ctx: grpcio::RpcContext<'_>,
    _req: bazel_protos::remote_execution::GetTreeRequest,
    _sink: grpcio::ServerStreamingSink<bazel_protos::remote_execution::GetTreeResponse>,
  ) {
    // Our client doesn't currently use get_tree, so we don't bother implementing it.
    // We will need to if the client starts wanting to use it.
    unimplemented!()
  }
}
