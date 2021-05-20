// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::time::Duration;

use futures::Future;
use rand::{thread_rng, Rng};
use tonic::{Code, Response, Status};

fn is_retryable(status: &Status) -> bool {
  matches!(
    status.code(),
    Code::Aborted
      | Code::Cancelled
      | Code::Internal
      | Code::ResourceExhausted
      | Code::Unavailable
      | Code::Unknown
  )
}

/// Retry a gRPC client operation using exponential back-off to delay between attempts.
#[inline]
pub async fn retry_call<T, C, F, Fut>(client: C, f: F) -> Result<Response<T>, Status>
where
  C: Clone,
  F: Fn(C) -> Fut,
  Fut: Future<Output = Result<Response<T>, Status>>,
{
  const INTERVAL_DURATION: Duration = Duration::from_millis(10);
  const MAX_RETRIES: u32 = 3;
  const MAX_BACKOFF_DURATION: Duration = Duration::from_secs(5);

  let mut last_error: Option<Status> = None;

  let mut num_retries = 0;
  while num_retries < MAX_RETRIES {
    // Delay before the next send attempt if this is a retry.
    if num_retries > 0 {
      let multiplier = thread_rng().gen_range(0..2_u32.pow(num_retries) + 1);
      let sleep_time = INTERVAL_DURATION * multiplier;
      let sleep_time = sleep_time.min(MAX_BACKOFF_DURATION);
      tokio::time::sleep(sleep_time).await;
    }

    let client2 = client.clone();
    let result_fut = f(client2);
    match result_fut.await {
      Ok(r) => return Ok(r),
      Err(status) => {
        if is_retryable(&status) {
          last_error = Some(status);
        } else {
          return Err(status);
        }
      }
    }

    num_retries += 1
  }

  Err(last_error.take().unwrap())
}
