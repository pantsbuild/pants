// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use futures::FutureExt;
use parking_lot::Mutex;
use remexec::action_cache_server::{ActionCache, ActionCacheServer};
use remexec::{ActionResult, GetActionResultRequest, UpdateActionResultRequest};
use tokio::time::sleep;
use tonic::transport::Server;
use tonic::{Request, Response, Status};

use grpc_util::hyper::AddrIncomingWithStream;
use hashing::{Digest, Fingerprint};
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;

pub struct StubActionCache {
  pub action_map: Arc<Mutex<HashMap<Fingerprint, ActionResult>>>,
  pub always_errors: Arc<AtomicBool>,
  local_addr: SocketAddr,
  shutdown_sender: Option<tokio::sync::oneshot::Sender<()>>,
}

impl Drop for StubActionCache {
  fn drop(&mut self) {
    self.shutdown_sender.take().unwrap().send(()).unwrap();
  }
}

#[derive(Clone)]
struct ActionCacheResponder {
  action_map: Arc<Mutex<HashMap<Fingerprint, ActionResult>>>,
  always_errors: Arc<AtomicBool>,
  read_delay: Duration,
  write_delay: Duration,
}

#[tonic::async_trait]
impl ActionCache for ActionCacheResponder {
  async fn get_action_result(
    &self,
    request: Request<GetActionResultRequest>,
  ) -> Result<Response<ActionResult>, Status> {
    sleep(self.read_delay).await;

    let request = request.into_inner();

    if self.always_errors.load(Ordering::SeqCst) {
      return Err(Status::unavailable("unavailable".to_owned()));
    }

    let action_digest: Digest = match require_digest(request.action_digest.as_ref()) {
      Ok(digest) => digest,
      Err(_) => {
        return Err(Status::internal(
          "Unable to extract action_digest.".to_owned(),
        ));
      }
    };

    let action_map = self.action_map.lock();
    let action_result = match action_map.get(&action_digest.hash) {
      Some(ar) => ar.clone(),
      None => {
        return Err(Status::not_found(format!(
          "ActionResult for Action {:?} does not exist",
          action_digest
        )));
      }
    };

    Ok(Response::new(action_result))
  }

  async fn update_action_result(
    &self,
    request: Request<UpdateActionResultRequest>,
  ) -> Result<Response<ActionResult>, Status> {
    sleep(self.write_delay).await;

    let request = request.into_inner();

    let action_digest: Digest = match require_digest(request.action_digest.as_ref()) {
      Ok(digest) => digest,
      Err(_) => {
        return Err(Status::internal(
          "Unable to extract action_digest.".to_owned(),
        ));
      }
    };

    let action_result = match request.action_result {
      Some(r) => r,
      None => {
        return Err(Status::invalid_argument(
          "Must provide action result".to_owned(),
        ))
      }
    };

    let mut action_map = self.action_map.lock();
    action_map.insert(action_digest.hash, action_result.clone());

    Ok(Response::new(action_result))
  }
}

impl StubActionCache {
  pub fn new() -> Result<Self, String> {
    Self::new_with_delays(0, 0)
  }

  pub fn new_with_delays(read_delay_ms: u64, write_delay_ms: u64) -> Result<Self, String> {
    let action_map = Arc::new(Mutex::new(HashMap::new()));
    let always_errors = Arc::new(AtomicBool::new(false));
    let responder = ActionCacheResponder {
      action_map: action_map.clone(),
      always_errors: always_errors.clone(),
      read_delay: Duration::from_millis(read_delay_ms),
      write_delay: Duration::from_millis(write_delay_ms),
    };

    let addr = "127.0.0.1:0"
      .to_string()
      .parse()
      .expect("failed to parse IP address");
    let incoming = hyper::server::conn::AddrIncoming::bind(&addr).expect("failed to bind port");
    let local_addr = incoming.local_addr();
    let incoming = AddrIncomingWithStream(incoming);

    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel();

    tokio::spawn(async move {
      let mut server = Server::builder();
      let router = server.add_service(ActionCacheServer::new(responder.clone()));

      router
        .serve_with_incoming_shutdown(incoming, shutdown_receiver.map(drop))
        .await
        .unwrap();
    });

    Ok(StubActionCache {
      action_map,
      always_errors,
      local_addr,
      shutdown_sender: Some(shutdown_sender),
    })
  }

  ///
  /// The address on which this server is listening over insecure HTTP transport.
  ///
  pub fn address(&self) -> String {
    format!("http://{}", self.local_addr)
  }

  ///
  /// Inserts the given action digest into the cache with the given outputs.
  ///
  pub fn insert(
    &self,
    action_digest: Digest,
    exit_code: i32,
    stdout_digest: Digest,
    stderr_digest: Digest,
  ) {
    let action_result = ActionResult {
      exit_code,
      stdout_digest: Some(stdout_digest.into()),
      stderr_digest: Some(stderr_digest.into()),
      ..ActionResult::default()
    };
    self
      .action_map
      .lock()
      .insert(action_digest.hash, action_result);
  }

  ///
  /// Get the result for the given action digest.
  ///
  pub fn get(&self, action_digest: Digest) -> Option<ActionResult> {
    self.action_map.lock().get(&action_digest.hash).cloned()
  }

  ///
  /// Returns the number of cache entries in the cache.
  ///
  pub fn len(&self) -> usize {
    self.action_map.lock().len()
  }
}
