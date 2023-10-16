// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use parking_lot::Mutex;
use remexec::action_cache_server::ActionCache;
use remexec::{ActionResult, GetActionResultRequest, UpdateActionResultRequest};
use tokio::time::sleep;
use tonic::{Request, Response, Status};

use hashing::{Digest, Fingerprint};
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;

pub struct ActionCacheHandle {
    pub action_map: Arc<Mutex<HashMap<Fingerprint, ActionResult>>>,
    pub always_errors: Arc<AtomicBool>,
}

impl ActionCacheHandle {
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
        self.action_map
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

#[derive(Clone)]
pub(crate) struct ActionCacheResponder {
    pub action_map: Arc<Mutex<HashMap<Fingerprint, ActionResult>>>,
    pub always_errors: Arc<AtomicBool>,
    pub read_delay: Duration,
    pub write_delay: Duration,
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
