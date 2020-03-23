use crate::{BackoffConfig, Retry, Serverset};
use maplit::hashset;
use std::time::Duration;
use testutil::owned_string_vec;

use futures::compat::Future01CompatExt;

#[tokio::test]
async fn retries() {
  let s = Serverset::new(
    owned_string_vec(&["good", "bad", "enough"]),
    |s| {
      if s == "bad" {
        Err(s.to_owned())
      } else {
        Ok(s.to_owned())
      }
    },
    3,
    BackoffConfig::new(Duration::from_millis(10), 2.0, Duration::from_millis(100)).unwrap(),
  )
  .unwrap();
  let mut saw = hashset![];
  for _ in 0..3 {
    saw.insert(
      Retry(s.clone())
        .all_errors_immediately(|v| v, 1)
        .compat()
        .await
        .unwrap(),
    );
  }
  assert_eq!(saw, hashset!["good".to_owned(), "enough".to_owned()]);
}

#[tokio::test]
async fn gives_up_on_enough_bad() {
  let s = Serverset::new(
    vec!["bad".to_owned()],
    |s| Err(s.to_owned()),
    1,
    BackoffConfig::new(Duration::from_millis(1), 1.0, Duration::from_millis(1)).unwrap(),
  )
  .unwrap();
  assert_eq!(
    Err(format!("Failed after 5 retries; last failure: bad")),
    Retry(s)
      .all_errors_immediately(|v: Result<u8, _>| v, 5)
      .compat()
      .await
  );
}
