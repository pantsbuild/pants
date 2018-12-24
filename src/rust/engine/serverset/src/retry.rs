use futures::{self, Future, IntoFuture};
use {Health, Serverset};

pub struct Retry<T>(pub Serverset<T>);

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
    futures::future::loop_fn(0_usize, move |i| {
      let serverset = serverset.clone();
      let f = f.clone();
      serverset
        .next()
        .and_then(move |(server, token)| {
          futures::future::ok(server).and_then(f).then(move |result| {
            let health = match &result {
              &Ok(_) => Health::Healthy,
              &Err(_) => Health::Unhealthy,
            };
            serverset.report_health(token, health);
            result
          })
        })
        .map(futures::future::Loop::Break)
        .or_else(move |err| {
          if i >= times {
            Err(format!("Failed after {} retries; last failure: {}", i, err))
          } else {
            Ok(futures::future::Loop::Continue(i + 1))
          }
        })
    })
  }
}

#[cfg(test)]
mod tests {
  use futures::Future;
  use futures_timer::TimerHandle;
  use std::time::Duration;
  use {BackoffConfig, Retry, Serverset};

  #[test]
  fn retries() {
    let s = Serverset::new(
      vec![Ok("good"), Err("bad".to_owned()), Ok("enough")],
      BackoffConfig::new(Duration::from_millis(10), 2.0, Duration::from_millis(100)).unwrap(),
      TimerHandle::default(),
    )
    .unwrap();
    let mut v = vec![];
    for _ in 0..3 {
      v.push(
        Retry(s.clone())
          .all_errors_immediately(|v| v, 1)
          .wait()
          .unwrap(),
      );
    }
    assert_eq!(vec!["good", "enough", "good"], v);
  }

  #[test]
  fn gives_up_on_enough_bad() {
    let s = Serverset::new(
      vec![Err("bad".to_owned())],
      BackoffConfig::new(Duration::from_millis(1), 1.0, Duration::from_millis(1)).unwrap(),
      TimerHandle::default(),
    )
    .unwrap();
    assert_eq!(
      Err(format!("Failed after 5 retries; last failure: bad")),
      Retry(s)
        .all_errors_immediately(|v: Result<u8, _>| v, 5)
        .wait()
    );
  }
}
