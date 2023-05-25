// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures::channel::oneshot;
use futures::future::{self, FutureExt};
use tokio::time::{sleep, timeout};

use crate::bounded::{balance, AsyncSemaphore, State, Task};

fn mk_semaphore(permits: usize) -> AsyncSemaphore {
  mk_semaphore_with_preemptible_duration(permits, Duration::from_millis(200))
}

fn mk_semaphore_with_preemptible_duration(
  permits: usize,
  preemptible_duration: Duration,
) -> AsyncSemaphore {
  let executor = task_executor::Executor::new();
  AsyncSemaphore::new(&executor, permits, preemptible_duration)
}

#[tokio::test]
async fn acquire_and_release() {
  let sema = mk_semaphore(1);

  sema.with_acquired(|_id| future::ready(())).await;
}

#[tokio::test]
async fn correct_semaphore_slot_ids() {
  let sema = mk_semaphore(2);
  let (tx1, rx1) = oneshot::channel();
  let (tx2, rx2) = oneshot::channel();
  let (tx3, rx3) = oneshot::channel();
  let (tx4, rx4) = oneshot::channel();

  let scale = Duration::from_millis(100);

  //Process 1
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    tx1.send(id).unwrap();
    sleep(2 * scale).await;
    future::ready(())
  }));
  //Process 2
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    sleep(scale).await;
    tx2.send(id).unwrap();
    future::ready(())
  }));
  //Process 3
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    sleep(scale).await;
    tx3.send(id).unwrap();
    future::ready(())
  }));

  sleep(5 * scale).await;

  //Process 4
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    sleep(scale).await;
    tx4.send(id).unwrap();
    future::ready(())
  }));

  let id1 = rx1.await.unwrap();
  let id2 = rx2.await.unwrap();
  let id3 = rx3.await.unwrap();
  let id4 = rx4.await.unwrap();

  // Process 1 should get ID 1, then process 2 should run with id 2 and complete, then process 3
  // should run in the same "slot" as process 2 and get the same id (2). Process 4 is scheduled
  // later and gets put into "slot" 1.
  assert_eq!(id1, 1);
  assert_eq!(id2, 2);
  assert_eq!(id3, 2);
  assert_eq!(id4, 1);
}

#[tokio::test]
async fn correct_semaphore_slot_ids_2() {
  let sema = mk_semaphore(4);
  let (tx1, rx1) = oneshot::channel();
  let (tx2, rx2) = oneshot::channel();
  let (tx3, rx3) = oneshot::channel();
  let (tx4, rx4) = oneshot::channel();
  let (tx5, rx5) = oneshot::channel();
  let (tx6, rx6) = oneshot::channel();
  let (tx7, rx7) = oneshot::channel();

  println!("Spawning process 1");
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    println!("Exec process 1");
    tx1.send(id).unwrap();
    sleep(Duration::from_millis(20)).await;
    future::ready(())
  }));
  println!("Spawning process 2");
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    println!("Exec process 2");
    tx2.send(id).unwrap();
    sleep(Duration::from_millis(20)).await;
    future::ready(())
  }));
  println!("Spawning process 3");
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    println!("Exec process 3");
    tx3.send(id).unwrap();
    sleep(Duration::from_millis(20)).await;
    future::ready(())
  }));
  println!("Spawning process 4");
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    println!("Exec process 4");
    tx4.send(id).unwrap();
    sleep(Duration::from_millis(20)).await;
    future::ready(())
  }));
  println!("Spawning process 5");
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    println!("Exec process 5");
    tx5.send(id).unwrap();
    sleep(Duration::from_millis(20)).await;
    future::ready(())
  }));
  println!("Spawning process 6");
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    println!("Exec process 6");
    tx6.send(id).unwrap();
    sleep(Duration::from_millis(20)).await;
    future::ready(())
  }));
  println!("Spawning process 7");
  tokio::spawn(sema.clone().with_acquired(move |id| async move {
    println!("Exec process 7");
    tx7.send(id).unwrap();
    sleep(Duration::from_millis(20)).await;
    future::ready(())
  }));

  let id1 = rx1.await.unwrap();
  let id2 = rx2.await.unwrap();
  let id3 = rx3.await.unwrap();
  let id4 = rx4.await.unwrap();
  let id5 = rx5.await.unwrap();
  let id6 = rx6.await.unwrap();
  let id7 = rx7.await.unwrap();

  assert_eq!(id1, 1);
  assert_eq!(id2, 2);
  assert_eq!(id3, 3);
  assert_eq!(id4, 4);
  assert_eq!(id5, 1);
  assert_eq!(id6, 2);
  assert_eq!(id7, 3);
}

#[tokio::test]
async fn at_most_n_acquisitions() {
  let sema = mk_semaphore(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();

  let (tx_thread1, acquired_thread1) = oneshot::channel();
  let (unblock_thread1, rx_thread1) = oneshot::channel();
  let (tx_thread2, acquired_thread2) = oneshot::channel();

  tokio::spawn(handle1.with_acquired(move |_id| {
    async {
      // Indicate that we've acquired, and then wait to be signaled to exit.
      tx_thread1.send(()).unwrap();
      rx_thread1.await.unwrap();
      future::ready(())
    }
  }));

  // Wait for thread1 to acquire, and then launch thread2.
  if let Err(_) = timeout(Duration::from_secs(5), acquired_thread1).await {
    panic!("thread1 didn't acquire.");
  }

  tokio::spawn(handle2.with_acquired(move |_id| {
    tx_thread2.send(()).unwrap();
    future::ready(())
  }));

  // thread2 should not signal until we unblock thread1.
  let acquired_thread2 =
    match future::select(sleep(Duration::from_millis(100)).boxed(), acquired_thread2).await {
      future::Either::Left((_, acquired_thread2)) => acquired_thread2,
      future::Either::Right(_) => {
        panic!("thread2 should not have acquired while thread1 was holding.")
      }
    };

  // Unblock thread1 and confirm that thread2 acquires.
  unblock_thread1.send(()).unwrap();
  if let Err(_) = timeout(Duration::from_secs(5), acquired_thread2).await {
    panic!("thread2 didn't acquire.");
  }
}

#[tokio::test]
async fn drop_while_waiting() {
  // This tests that a task in the waiters queue of the semaphore is removed
  // from the queue when the future that is was polling gets dropped.
  //
  // First we acquire the semaphore with a "process" which hangs until we send
  // it a signal via the unblock_thread1 channel. This means that any futures that
  // try to acquire the semaphore will be queued up until we unblock thread .
  //
  // Next we spawn a future on a second thread that tries to acquire the semaphore,
  // and get added to the waiters queue, we drop that future after a Delay timer
  // completes. The drop should cause the task to be removed from the waiters queue.
  //
  // Then we spawn a 3rd future that tries to acquire the semaphore but cannot
  // because thread1 still has the only permit. After this future is added to the waiters
  // we unblock thread1 and wait for a signal from the thread3 that it acquires.
  //
  // If the SECOND future was not removed from the waiters queue we would not get a signal
  // that thread3 acquired the lock because the 2nd task would be blocking the queue trying to
  // poll a non existent future.
  let sema = mk_semaphore(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();
  let handle3 = sema.clone();

  let (tx_thread1, acquired_thread1) = oneshot::channel();
  let (unblock_thread1, rx_thread1) = oneshot::channel();
  let (tx_thread3, acquired_thread3) = oneshot::channel();
  let (unblock_thread3, rx_thread3) = oneshot::channel();
  let (tx_thread2_attempt_1, did_not_acquire_thread2_attempt_1) = oneshot::channel();

  tokio::spawn(handle1.with_acquired(move |_id| {
    async {
      // Indicate that we've acquired, and then wait to be signaled to exit.
      tx_thread1.send(()).unwrap();
      rx_thread1.await.unwrap();
      future::ready(())
    }
  }));

  // Wait for thread1 to acquire, and then launch thread2.
  if let Err(_) = timeout(Duration::from_secs(5), acquired_thread1).await {
    panic!("thread1 didn't acquire.");
  }

  // thread2 will wait for a little while, but then drop its PermitFuture to give up on waiting.
  tokio::spawn(async move {
    let permit_future = handle2.acquire(1).boxed();
    let delay_future = sleep(Duration::from_millis(100)).boxed();
    let raced_result = future::select(delay_future, permit_future).await;
    // We expect to have timed out, because the other Future will not resolve until asked.
    match raced_result {
      future::Either::Left(_) => {}
      future::Either::Right(_) => panic!("Expected to time out."),
    };
    tx_thread2_attempt_1.send(()).unwrap();
  });

  tokio::spawn(handle3.with_acquired(move |_id| {
    async {
      // Indicate that we've acquired, and then wait to be signaled to exit.
      tx_thread3.send(()).unwrap();
      rx_thread3.await.unwrap();
      future::ready(())
    }
  }));

  // thread2 should signal that it did not successfully acquire for the first attempt.
  if let Err(_) = timeout(Duration::from_secs(5), did_not_acquire_thread2_attempt_1).await {
    panic!("thread2 should have failed to acquire by now.");
  }

  // Unblock thread1 and confirm that thread3 acquires.
  unblock_thread1.send(()).unwrap();
  if let Err(_) = timeout(Duration::from_secs(5), acquired_thread3).await {
    panic!("thread3 didn't acquire.");
  }
  unblock_thread3.send(()).unwrap();
}

#[tokio::test]
async fn dropped_future_is_removed_from_queue() {
  let sema = mk_semaphore(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();

  let (tx_thread1, acquired_thread1) = oneshot::channel();
  let (unblock_thread1, rx_thread1) = oneshot::channel::<()>();
  let (tx_thread2, gave_up_thread2) = oneshot::channel();
  let (unblock_thread2, rx_thread2) = oneshot::channel();

  let join_handle1 = tokio::spawn(handle1.with_acquired(move |_id| {
    async {
      // Indicate that we've acquired, and then wait to be signaled to exit.
      tx_thread1.send(()).unwrap();
      rx_thread1.await.unwrap();
      future::ready(())
    }
  }));

  // Wait for the first handle to acquire, and then launch thread2.
  if let Err(_) = timeout(Duration::from_secs(5), acquired_thread1).await {
    panic!("thread1 didn't acquire.");
  }
  let waiter = handle2.with_acquired(|_id| future::ready(()));
  let join_handle2 = tokio::spawn(async move {
    match future::select(sleep(Duration::from_millis(100)).boxed(), waiter.boxed()).await {
      future::Either::Left(((), waiter_future)) => {
        tx_thread2.send(()).unwrap();
        rx_thread2.await.unwrap();
        drop(waiter_future);
      }
      future::Either::Right(_) => {
        panic!("The sleep result should always be ready first!");
      }
    }
  });

  // Wait for thread2 to give up on acquiring.
  if let Err(_) = timeout(Duration::from_secs(5), gave_up_thread2).await {
    panic!("thread2 didn't give up on acquiring.");
  }
  assert_eq!(0, sema.available_permits());

  // Then cause it to drop its attempt.
  unblock_thread2.send(()).unwrap();
  if let Err(_) = timeout(Duration::from_secs(5), join_handle2).await {
    panic!("thread2 didn't exit.");
  }
  assert_eq!(0, sema.available_permits());

  // Finally, release in thread1.
  unblock_thread1.send(()).unwrap();
  if let Err(_) = timeout(Duration::from_secs(5), join_handle1).await {
    panic!("thread1 didn't exit.");
  }
  assert_eq!(1, sema.available_permits());
}

#[tokio::test]
async fn preemption() {
  let ten_secs = Duration::from_secs(10);
  let sema = mk_semaphore_with_preemptible_duration(2, ten_secs);

  // Acquire a permit which will take all concurrency, and confirm that it doesn't get preempted.
  let permit1 = sema.acquire(2).await;
  assert_eq!(2, permit1.concurrency());
  if let Ok(_) = timeout(ten_secs / 100, permit1.notified_concurrency_changed()).await {
    panic!("permit1 should not have been preempted.");
  }

  // Acquire another permit, and confirm that it doesn't get preempted.
  let permit2 = sema.acquire(2).await;
  if let Ok(_) = timeout(ten_secs / 100, permit2.notified_concurrency_changed()).await {
    panic!("permit2 should not have been preempted.");
  }

  // But that permit1 does get preempted.
  if let Err(_) = timeout(ten_secs, permit1.notified_concurrency_changed()).await {
    panic!("permit1 should have been preempted.");
  }

  assert_eq!(1, permit1.concurrency());
  assert_eq!(1, permit2.concurrency());
}

/// Given Tasks as triples of desired, actual, and expected concurrency (all of which are
/// assumed to be preemptible), assert that the expected concurrency is applied.
fn test_balance(
  total_concurrency: usize,
  expected_preempted: usize,
  task_defs: Vec<(usize, usize, usize)>,
) {
  let ten_minutes_from_now = Instant::now() + Duration::from_secs(10 * 60);
  let tasks = task_defs
    .iter()
    .enumerate()
    .map(|(id, (desired, actual, _))| {
      Arc::new(Task::new(id, *desired, *actual, ten_minutes_from_now))
    })
    .collect::<Vec<_>>();

  let mut state = State::new_for_tests(total_concurrency, tasks.clone());

  assert_eq!(expected_preempted, balance(Instant::now(), &mut state));
  for (task, (_, _, expected)) in tasks.iter().zip(task_defs.into_iter()) {
    assert_eq!(expected, task.concurrency());
  }
}

#[tokio::test]
async fn balance_noop() {
  test_balance(2, 0, vec![(1, 1, 1), (1, 1, 1)]);
}

#[tokio::test]
async fn balance_overcommitted() {
  // Preempt the first Task and give it one slot, without adjusting the second task.
  test_balance(2, 1, vec![(2, 2, 1), (1, 1, 1)]);
}

#[tokio::test]
async fn balance_undercommitted() {
  // Should preempt both Tasks to give them more concurrency.
  test_balance(4, 2, vec![(2, 1, 2), (2, 1, 2)]);
}
