use crate::{retry, BackoffConfig, Serverset};

use std::time::Duration;

use maplit::hashset;
use testutil::owned_string_vec;

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
      retry::all_errors_immediately(&s, 1, |v| async move { v })
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
    retry::all_errors_immediately(&s, 5, |v: Result<u8, _>| async move { v }).await
  );
}
