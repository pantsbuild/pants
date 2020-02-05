use crate::{Health, Serverset};
use futures01::{future, Future, IntoFuture};

pub struct Retry<T: Clone>(pub Serverset<T>);

impl<T: Clone + Send + Sync + 'static> Retry<T> {
  ///
  /// Runs `f` up to `times` times, taking servers from the underlying serverset.
  ///
  /// Will retry any time `f` produces an error. The underlying serverset may lead to backoff
  /// between attempts, but the Retry implementation itself will not.
  ///
  pub fn all_errors_immediately<
    Value: Send + 'static,
    Fut: Future<Item = Value, Error = String>,
    IntoFut: IntoFuture<Future = Fut, Item = Value, Error = String>,
    F: FnMut(T) -> IntoFut + Send + Sync + Clone + 'static,
  >(
    &self,
    f: F,
    times: usize,
  ) -> impl Future<Item = Value, Error = String> {
    let serverset = self.0.clone();
    future::loop_fn(0_usize, move |i| {
      let serverset = serverset.clone();
      let f = f.clone();
      serverset
        .next()
        .and_then(move |(server, token)| {
          future::ok(server).and_then(f).then(move |result| {
            let health = match &result {
              &Ok(_) => Health::Healthy,
              &Err(_) => Health::Unhealthy,
            };
            serverset.report_health(token, health);
            result
          })
        })
        .map(future::Loop::Break)
        .or_else(move |err| {
          if i >= times {
            Err(format!("Failed after {} retries; last failure: {}", i, err))
          } else {
            Ok(future::Loop::Continue(i + 1))
          }
        })
    })
  }
}
