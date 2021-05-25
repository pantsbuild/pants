// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::time::Duration;

use futures::Future;
use rand::{thread_rng, Rng};
use tonic::{Code, Status};

pub fn status_is_retryable(status: &Status) -> bool {
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
pub async fn retry_call<T, E, C, F, G, Fut>(client: C, f: F, is_retryable: G) -> Result<T, E>
where
  C: Clone,
  F: Fn(C) -> Fut,
  G: Fn(&E) -> bool,
  Fut: Future<Output = Result<T, E>>,
{
  const INTERVAL_DURATION: Duration = Duration::from_millis(20);
  const MAX_RETRIES: u32 = 3;
  const MAX_BACKOFF_DURATION: Duration = Duration::from_secs(5);

  let mut num_retries = 0;
  let last_error = loop {
    // Delay before the next send attempt if this is a retry.
    if num_retries > 0 {
      let multiplier = thread_rng().gen_range(0..2_u32.pow(num_retries) + 1);
      let sleep_time = INTERVAL_DURATION * multiplier;
      let sleep_time = sleep_time.min(MAX_BACKOFF_DURATION);
      tokio::time::sleep(sleep_time).await;
    }

    let client2 = client.clone();
    let result_fut = f(client2);
    let last_error = match result_fut.await {
      Ok(r) => return Ok(r),
      Err(err) => {
        if is_retryable(&err) {
          err
        } else {
          return Err(err);
        }
      }
    };

    num_retries += 1;

    if num_retries >= MAX_RETRIES {
      break last_error;
    }
  };

  Err(last_error)
}

#[cfg(test)]
mod tests {
  use std::collections::VecDeque;
  use std::sync::Arc;

  use parking_lot::Mutex;

  use super::retry_call;

  #[derive(Clone, Debug)]
  struct MockClient<T> {
    values: Arc<Mutex<VecDeque<T>>>,
  }

  impl<T> MockClient<T> {
    pub fn new(values: Vec<T>) -> Self {
      MockClient {
        values: Arc::new(Mutex::new(values.into())),
      }
    }

    async fn next(&self) -> T {
      let mut values = self.values.lock();
      values.pop_front().unwrap()
    }
  }

  #[derive(Clone, Debug, Eq, PartialEq)]
  struct MockError(bool, &'static str);

  #[tokio::test]
  async fn retry_call_works_as_expected() {
    let client = MockClient::new(vec![
      Err(MockError(true, "first")),
      Err(MockError(true, "second")),
      Ok(3isize),
      Ok(4isize),
    ]);
    let result = retry_call(
      client.clone(),
      |client| async move { client.next().await },
      |err| err.0,
    )
    .await;
    assert_eq!(result, Ok(3isize));
    assert_eq!(client.values.lock().len(), 1);

    let client = MockClient::new(vec![
      Err(MockError(true, "first")),
      Err(MockError(false, "second")),
      Ok(3isize),
      Ok(4isize),
    ]);
    let result = retry_call(
      client.clone(),
      |client| async move { client.next().await },
      |err| err.0,
    )
    .await;
    assert_eq!(result, Err(MockError(false, "second")));
    assert_eq!(client.values.lock().len(), 2);

    let client = MockClient::new(vec![
      Err(MockError(true, "first")),
      Err(MockError(true, "second")),
      Err(MockError(true, "third")),
      Ok(1isize),
    ]);
    let result = retry_call(
      client.clone(),
      |client| async move { client.next().await },
      |err| err.0,
    )
    .await;
    assert_eq!(result, Err(MockError(true, "third")));
    assert_eq!(client.values.lock().len(), 1);
  }
}
