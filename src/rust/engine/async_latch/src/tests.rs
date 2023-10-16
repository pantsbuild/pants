use std::time::Duration;

use tokio::time::sleep;

use crate::AsyncLatch;

#[tokio::test]
async fn basic() {
    let latch = AsyncLatch::new();

    let mut join = tokio::spawn({
        let latch = latch.clone();
        async move { latch.triggered().await }
    });

    // Ensure that `triggered` doesn't return until `trigger` has been called.
    tokio::select! {
      _ = sleep(Duration::from_secs(1)) => {},
      _ = &mut join => { panic!("Background task should have continued to wait.") }
    }
    latch.trigger();
    join.await.unwrap();

    // And that calling `trigger` again is harmless.
    latch.trigger();
}
