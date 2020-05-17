use crate::AsyncSemaphore;

use std::time::Duration;

use futures::channel::oneshot;
use futures::future::{self, FutureExt};

use tokio;
use tokio::time::{delay_for, timeout};

#[tokio::test]
async fn acquire_and_release() {
  let sema = AsyncSemaphore::new(1);

  sema.with_acquired(|| future::ready(())).await;
}

#[tokio::test]
async fn at_most_n_acquisitions() {
  let sema = AsyncSemaphore::new(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();

  let (tx_thread1, acquired_thread1) = oneshot::channel();
  let (unblock_thread1, rx_thread1) = oneshot::channel();
  let (tx_thread2, acquired_thread2) = oneshot::channel();

  tokio::spawn(handle1.with_acquired(move || {
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

  tokio::spawn(handle2.with_acquired(move || {
    tx_thread2.send(()).unwrap();
    future::ready(())
  }));

  // thread2 should not signal until we unblock thread1.
  let acquired_thread2 =
    match future::select(delay_for(Duration::from_millis(100)), acquired_thread2).await {
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
  let sema = AsyncSemaphore::new(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();
  let handle3 = sema.clone();

  let (tx_thread1, acquired_thread1) = oneshot::channel();
  let (unblock_thread1, rx_thread1) = oneshot::channel();
  let (tx_thread3, acquired_thread3) = oneshot::channel();
  let (unblock_thread3, rx_thread3) = oneshot::channel();
  let (tx_thread2_attempt_1, did_not_acquire_thread2_attempt_1) = oneshot::channel();

  tokio::spawn(handle1.with_acquired(move || {
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
  tokio::spawn(future::lazy(move |_| {
    let permit_future = handle2.acquire();
    let delay_future = delay_for(Duration::from_millis(100));
    future::select(delay_future, permit_future).map(move |raced_result| {
      // We expect to have timed out, because the other Future will not resolve until asked.
      match raced_result {
        future::Either::Left(_) => {}
        future::Either::Right(_) => panic!("Expected to time out."),
      };
      tx_thread2_attempt_1.send(()).unwrap();
    })
  }));

  tokio::spawn(handle3.with_acquired(move || {
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
  let sema = AsyncSemaphore::new(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();

  let (tx_thread1, acquired_thread1) = oneshot::channel();
  let (unblock_thread1, rx_thread1) = oneshot::channel::<()>();
  let (tx_thread2, gave_up_thread2) = oneshot::channel();
  let (unblock_thread2, rx_thread2) = oneshot::channel();

  let join_handle1 = tokio::spawn(handle1.with_acquired(move || {
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
  let waiter = handle2.with_acquired(|| future::ready(()));
  let join_handle2 = tokio::spawn(async move {
    match future::select(delay_for(Duration::from_millis(100)), waiter.boxed()).await {
      future::Either::Left(((), waiter_future)) => {
        tx_thread2.send(()).unwrap();
        rx_thread2.await.unwrap();
        drop(waiter_future);
        ()
      }
      future::Either::Right(_) => {
        panic!("The delay_for result should always be ready first!");
      }
    }
  });

  // Wait for thread2 to give up on acquiring.
  if let Err(_) = timeout(Duration::from_secs(5), gave_up_thread2).await {
    panic!("thread2 didn't give up on acquiring.");
  }
  assert_eq!(1, sema.num_waiters());

  // Then cause it to drop its attempt.
  unblock_thread2.send(()).unwrap();
  if let Err(_) = timeout(Duration::from_secs(5), join_handle2).await {
    panic!("thread2 didn't exit.");
  }
  assert_eq!(0, sema.num_waiters());

  // Finally, release in thread1.
  unblock_thread1.send(()).unwrap();
  if let Err(_) = timeout(Duration::from_secs(5), join_handle1).await {
    panic!("thread1 didn't exit.");
  }
  assert_eq!(0, sema.num_waiters());
}
