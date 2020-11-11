use crate::{Health, Serverset};

use std::future::Future;

///
/// Runs `f` up to `times` times, taking servers from the given serverset.
///
/// Will retry any time `f` produces an error. The underlying serverset may lead to backoff
/// between attempts, but the Retry implementation itself will not.
///
pub async fn all_errors_immediately<
  T: Clone + Send + Sync + 'static,
  Value: Send,
  Fut: Future<Output = Result<Value, String>>,
  F: Fn(T) -> Fut,
>(
  serverset: &Serverset<T>,
  times: usize,
  f: F,
) -> Result<Value, String> {
  let mut i = 0;
  loop {
    // Request a server, and run the function.
    let (server, token) = serverset.next().await?;
    let result = f(server).await;

    // If the function failed, report the server unhealthy and try again.
    if let Err(e) = result {
      serverset.report_health(token, Health::Unhealthy);
      if i >= times {
        return Err(format!("Failed after {} retries; last failure: {}", i, e));
      }
      i += 1;
      continue;
    }

    // Otherwise, we're done!
    serverset.report_health(token, Health::Healthy);
    return result;
  }
}
