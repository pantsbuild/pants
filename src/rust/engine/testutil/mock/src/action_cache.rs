// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
clippy::all,
clippy::default_trait_access,
clippy::expl_impl_clone_on_copy,
clippy::if_not_else,
clippy::needless_continue,
clippy::unseparated_literal_suffix,
// TODO: Falsely triggers for async/await:
//   see https://github.com/rust-lang/rust-clippy/issues/5360
// clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
clippy::len_without_is_empty,
clippy::redundant_field_names,
clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::collections::HashMap;
use std::convert::TryInto;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use bazel_protos::remote_execution::{
  ActionResult, GetActionResultRequest, UpdateActionResultRequest,
};
use grpcio::{RpcContext, UnarySink};
use hashing::{Digest, Fingerprint};
use parking_lot::Mutex;

pub struct StubActionCache {
  server_transport: grpcio::Server,
  pub action_map: Arc<Mutex<HashMap<Fingerprint, ActionResult>>>,
  pub always_errors: Arc<AtomicBool>,
}

#[derive(Clone)]
struct ActionCacheResponder {
  action_map: Arc<Mutex<HashMap<Fingerprint, ActionResult>>>,
  always_errors: Arc<AtomicBool>,
}

impl bazel_protos::remote_execution_grpc::ActionCache for ActionCacheResponder {
  fn get_action_result(
    &self,
    _: RpcContext<'_>,
    req: GetActionResultRequest,
    sink: UnarySink<ActionResult>,
  ) {
    if self.always_errors.load(Ordering::SeqCst) {
      sink.fail(grpcio::RpcStatus::new(
        grpcio::RpcStatusCode::UNAVAILABLE,
        Some("unavailable".to_owned()),
      ));
      return;
    }

    let action_digest: Digest = match req.get_action_digest().try_into() {
      Ok(digest) => digest,
      Err(_) => {
        sink.fail(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INTERNAL,
          Some("Unable to extract action_digest.".to_owned()),
        ));
        return;
      }
    };

    let action_map = self.action_map.lock();
    let action_result = match action_map.get(&action_digest.0) {
      Some(ar) => ar.clone(),
      None => {
        sink.fail(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::NOT_FOUND,
          Some(format!(
            "ActionResult for Action {:?} does not exist",
            action_digest
          )),
        ));
        return;
      }
    };

    sink.success(action_result);
  }

  fn update_action_result(
    &self,
    _: RpcContext<'_>,
    req: UpdateActionResultRequest,
    sink: UnarySink<ActionResult>,
  ) {
    let action_digest: Digest = match req.get_action_digest().try_into() {
      Ok(digest) => digest,
      Err(_) => {
        sink.fail(grpcio::RpcStatus::new(
          grpcio::RpcStatusCode::INTERNAL,
          Some("Unable to extract action_digest.".to_owned()),
        ));
        return;
      }
    };

    let mut action_map = self.action_map.lock();
    action_map.insert(action_digest.0, req.get_action_result().clone());

    sink.success(req.get_action_result().clone());
  }
}

impl StubActionCache {
  pub fn new() -> Result<Self, String> {
    let action_map = Arc::new(Mutex::new(HashMap::new()));
    let always_errors = Arc::new(AtomicBool::new(false));
    let responder = ActionCacheResponder {
      action_map: action_map.clone(),
      always_errors: always_errors.clone(),
    };

    let env = Arc::new(grpcio::Environment::new(1));
    let mut server_transport = grpcio::ServerBuilder::new(env)
      .register_service(bazel_protos::remote_execution_grpc::create_action_cache(
        responder,
      ))
      .bind("127.0.0.1", 0)
      .build()
      .unwrap();
    server_transport.start();

    Ok(StubActionCache {
      server_transport,
      action_map,
      always_errors,
    })
  }

  ///
  /// The address on which this server is listening over insecure HTTP transport.
  ///
  pub fn address(&self) -> String {
    let bind_addr = self.server_transport.bind_addrs().next().unwrap();
    format!("{}:{}", bind_addr.0, bind_addr.1)
  }
}
