use crate::AsyncValue;

use std::time::Duration;

use tokio;
use tokio::time::delay_for;

#[tokio::test]
async fn send() {
  let (_value, sender, receiver) = AsyncValue::new();
  let _send_task = tokio::spawn(async move { sender.send(42) });
  assert_eq!(Some(42), receiver.recv().await);
}

#[tokio::test]
async fn cancel_explicit() {
  let (value, mut sender, receiver) = AsyncValue::<()>::new();

  // A task that will never do any meaningful work, and just wait to be canceled.
  let _send_task = tokio::spawn(async move { sender.closed().await });

  // Ensure that a value is not received.
  tokio::select! {
    _ = delay_for(Duration::from_secs(1)) => {},
    _ = receiver.recv() => { panic!("Should have continued to wait.") }
  }

  // Then drop the AsyncValue and confirm that the background task returns.
  std::mem::drop(value);
  assert_eq!(None, receiver.recv().await);
}

#[tokio::test]
async fn cancel_implicit() {
  let (value, mut sender, receiver) = AsyncValue::<()>::new();

  // A task that will never do any meaningful work, and just wait to be canceled.
  let send_task = tokio::spawn(async move { sender.closed().await });

  // Ensure that a value is not received.
  tokio::select! {
    _ = delay_for(Duration::from_secs(1)) => {},
    _ = receiver.recv() => { panic!("Should have continued to wait.") }
  }

  // Then drop the only receiver and confirm that the background task returns, and that new
  // receivers cannot be created.
  std::mem::drop(receiver);
  send_task.await.unwrap();
  assert!(value.receiver().is_none());
}
