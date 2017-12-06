use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use bazel_protos;
use futures;
use grpcio;

use futures::Future;
use Fingerprint;

///
/// Implements the ContentAddressableStorage gRPC API, answering read requests with either known
/// content, NotFound for valid but unknown content, or InvalidArguments for bad arguments.
///
pub struct StubCAS {
  server_transport: grpcio::Server,
  request_count: Arc<Mutex<usize>>,
}

impl StubCAS {
  ///
  /// # Arguments
  /// * `chunk_size_bytes` - The maximum number of bytes of content to include per streamed message.
  ///                        Messages will saturate until the last one, which may be smaller than
  ///                        this value.
  ///                        If a negative value is given, all requests will receive an error.
  /// * `blobs`            - Known Fingerprints and their content responses. These are not checked
  ///                        for correctness.
  pub fn new(chunk_size_bytes: i64, blobs: HashMap<Fingerprint, Vec<u8>>) -> StubCAS {
    let env = Arc::new(grpcio::Environment::new(1));
    let request_count = Arc::new(Mutex::new(0));
    let responder = StubCASResponder {
      chunk_size_bytes,
      blobs,
      request_count: request_count.clone(),
    };
    let mut server_transport = grpcio::ServerBuilder::new(env)
      .register_service(bazel_protos::bytestream_grpc::create_byte_stream(
        responder.clone(),
      ))
      .bind("localhost", 0)
      .build()
      .unwrap();
    server_transport.start();

    let cas = StubCAS {
      server_transport,
      request_count,
    };
    cas
  }

  pub fn empty() -> StubCAS {
    StubCAS::new(1024, HashMap::new())
  }

  pub fn always_errors() -> StubCAS {
    StubCAS::new(-1, HashMap::new())
  }

  ///
  /// The address on which this server is listening over insecure HTTP transport.
  ///
  pub fn address(&self) -> String {
    let bind_addr = self.server_transport.bind_addrs().first().unwrap();
    format!("{}:{}", bind_addr.0, bind_addr.1)
  }

  pub fn request_count(&self) -> usize {
    self.request_count.lock().unwrap().clone()
  }
}

#[derive(Clone, Debug)]
pub struct StubCASResponder {
  chunk_size_bytes: i64,
  blobs: HashMap<Fingerprint, Vec<u8>>,
  pub request_count: Arc<Mutex<usize>>,
}

impl StubCASResponder {
  fn read_internal(
    &self,
    req: bazel_protos::bytestream::ReadRequest,
  ) -> Result<Vec<bazel_protos::bytestream::ReadResponse>, grpcio::RpcStatus> {
    let parts: Vec<_> = req.get_resource_name().splitn(4, "/").collect();
    if parts.len() != 4 || parts.get(0) != Some(&"") || parts.get(1) != Some(&"blobs") {
      return Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::InvalidArgument,
        Some(format!(
          "Bad resource name format {} - want /blobs/some-sha256/size",
          req.get_resource_name()
        )),
      ));
    }
    let digest = parts.get(2).unwrap();
    let fingerprint = Fingerprint::from_hex_string(digest).map_err(|e| {
      grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::InvalidArgument,
        Some(format!("Bad digest {}: {}", digest, e)),
      )
    })?;
    if self.chunk_size_bytes < 0 {
      return Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::Internal,
        Some("StubCAS is configured to always fail".to_owned()),
      ));
    }
    let maybe_bytes = self.blobs.get(&fingerprint);
    match maybe_bytes {
      Some(bytes) => Ok(
        bytes
          .chunks(self.chunk_size_bytes as usize)
          .map(|b| {
            let mut resp = bazel_protos::bytestream::ReadResponse::new();
            resp.set_data(b.to_vec());
            resp
          })
          .collect(),
      ),
      None => Err(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::NotFound,
        Some(format!("Did not find digest {}", fingerprint)),
      )),
    }
  }

  ///
  /// Sends a stream of responses down a sink, in ctx's threadpool.
  ///
  fn send<Item, S>(
    &self,
    ctx: grpcio::RpcContext,
    sink: grpcio::ServerStreamingSink<Item>,
    stream: S,
  ) where
    Item: Send + 'static,
    S: futures::Stream<Item = (Item, grpcio::WriteFlags), Error = grpcio::Error> + Send + 'static,
  {
    ctx.spawn(stream.forward(sink).map(|_| ()).map_err(|_| ()));
  }
}

impl bazel_protos::bytestream_grpc::ByteStream for StubCASResponder {
  fn read(
    &self,
    ctx: grpcio::RpcContext,
    req: bazel_protos::bytestream::ReadRequest,
    sink: grpcio::ServerStreamingSink<bazel_protos::bytestream::ReadResponse>,
  ) {
    {
      let mut request_count = self.request_count.lock().unwrap();
      *request_count = *request_count + 1;
    }
    match self.read_internal(req) {
      Ok(response) => {
        self.send(
          ctx,
          sink,
          futures::stream::iter_ok(response.into_iter().map(|chunk| {
            (chunk, grpcio::WriteFlags::default())
          })),
        )
      }
      Err(err) => {
        sink.fail(err);
      }
    }
  }

  fn write(
    &self,
    _ctx: grpcio::RpcContext,
    _stream: grpcio::RequestStream<bazel_protos::bytestream::WriteRequest>,
    sink: grpcio::ClientStreamingSink<bazel_protos::bytestream::WriteResponse>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::Unimplemented,
      None,
    ));
  }

  fn query_write_status(
    &self,
    _ctx: grpcio::RpcContext,
    _req: bazel_protos::bytestream::QueryWriteStatusRequest,
    sink: grpcio::UnarySink<bazel_protos::bytestream::QueryWriteStatusResponse>,
  ) {
    sink.fail(grpcio::RpcStatus::new(
      grpcio::RpcStatusCode::Unimplemented,
      None,
    ));
  }
}
