// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::time::Duration;

use futures::Future;
use rand::RngExt;
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
pub async fn retry_call<T, E, C, F, G, Fut>(
    client: C,
    mut f: F,
    is_retryable: G,
    max_attempts: usize,
) -> Result<T, E>
where
    C: Clone,
    F: FnMut(C, u32) -> Fut,
    G: Fn(&E) -> bool,
    Fut: Future<Output = Result<T, E>>,
{
    const INTERVAL_DURATION: Duration = Duration::from_millis(20);
    const MAX_BACKOFF_DURATION: Duration = Duration::from_secs(5);

    let mut num_retries = 0;
    let last_error = loop {
        // Delay before the next send attempt if this is a retry.
        if num_retries > 0 {
            // NB: saturating_pow because `max_attempts` is user-configurable; the sleep is capped
            // just below anyway.
            let multiplier = rand::rng().random_range(0..=2_u32.saturating_pow(num_retries));
            let sleep_time = INTERVAL_DURATION * multiplier;
            let sleep_time = sleep_time.min(MAX_BACKOFF_DURATION);
            tokio::time::sleep(sleep_time).await;
        }

        let client2 = client.clone();
        let result_fut = f(client2, num_retries);
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

        if num_retries as usize >= max_attempts {
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
        // several retryable errors
        let client = MockClient::new(vec![
            Err(MockError(true, "first")),
            Err(MockError(true, "second")),
            Ok(3_isize),
            Ok(4_isize),
        ]);
        let mut expected_attempt = 0;
        let result = retry_call(
            client.clone(),
            |client, attempt| {
                // check `attempt` is being passed through as expected: starting with 0 for the first
                // call, and incriminating for each one after
                assert_eq!(attempt, expected_attempt);
                expected_attempt += 1;

                async move { client.next().await }
            },
            |err| err.0,
            3,
        )
        .await;
        assert_eq!(result, Ok(3_isize));
        assert_eq!(client.values.lock().len(), 1);

        // a non retryable error
        let client = MockClient::new(vec![
            Err(MockError(true, "first")),
            Err(MockError(false, "second")),
            Ok(3_isize),
            Ok(4_isize),
        ]);
        let result = retry_call(
            client.clone(),
            |client, _| async move { client.next().await },
            |err| err.0,
            3,
        )
        .await;
        assert_eq!(result, Err(MockError(false, "second")));
        assert_eq!(client.values.lock().len(), 2);

        // retryable errors, but too many
        let client = MockClient::new(vec![
            Err(MockError(true, "first")),
            Err(MockError(true, "second")),
            Err(MockError(true, "third")),
            Ok(1_isize),
        ]);
        let result = retry_call(
            client.clone(),
            |client, _| async move { client.next().await },
            |err| err.0,
            3,
        )
        .await;
        assert_eq!(result, Err(MockError(true, "third")));
        assert_eq!(client.values.lock().len(), 1);
    }

    #[tokio::test]
    async fn retry_call_respects_max_attempts() {
        // succeeds on the 5th attempt, more than the historical default of 3 would allow
        let client = MockClient::new(vec![
            Err(MockError(true, "first")),
            Err(MockError(true, "second")),
            Err(MockError(true, "third")),
            Err(MockError(true, "fourth")),
            Ok(5_isize),
        ]);
        let result = retry_call(
            client.clone(),
            |client, _| async move { client.next().await },
            |err| err.0,
            5,
        )
        .await;
        assert_eq!(result, Ok(5_isize));
        assert_eq!(client.values.lock().len(), 0);

        // a single attempt: even a retryable error is returned immediately
        let client = MockClient::new(vec![Err(MockError(true, "first")), Ok(2_isize)]);
        let result = retry_call(
            client.clone(),
            |client, _| async move { client.next().await },
            |err| err.0,
            1,
        )
        .await;
        assert_eq!(result, Err(MockError(true, "first")));
        assert_eq!(client.values.lock().len(), 1);
    }
}
