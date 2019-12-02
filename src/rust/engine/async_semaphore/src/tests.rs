use crate::AsyncSemaphore;
use futures::{future, Future};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use tokio_timer::Delay;

#[test]
fn acquire_and_release() {
  let sema = AsyncSemaphore::new(1);

  sema
    .with_acquired(|| future::ok::<_, ()>(()))
    .wait()
    .unwrap();
}

#[test]
fn at_most_n_acquisitions() {
  let sema = AsyncSemaphore::new(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();

  let (tx_thread1, acquired_thread1) = mpsc::channel();
  let (unblock_thread1, rx_thread1) = mpsc::channel();
  let (tx_thread2, acquired_thread2) = mpsc::channel();

  thread::spawn(move || {
    handle1
      .with_acquired(move || {
        // Indicate that we've acquired, and then wait to be signaled to exit.
        tx_thread1.send(()).unwrap();
        rx_thread1.recv().unwrap();
        future::ok::<_, ()>(())
      })
      .wait()
      .unwrap();
  });

  // Wait for thread1 to acquire, and then launch thread2.
  acquired_thread1
    .recv_timeout(Duration::from_secs(5))
    .expect("thread1 didn't acquire.");

  thread::spawn(move || {
    handle2
      .with_acquired(move || {
        tx_thread2.send(()).unwrap();
        future::ok::<_, ()>(())
      })
      .wait()
      .unwrap();
  });

  // thread2 should not signal until we unblock thread1.
  match acquired_thread2.recv_timeout(Duration::from_millis(100)) {
    Err(_) => (),
    Ok(_) => panic!("thread2 should not have acquired while thread1 was holding."),
  }

  // Unblock thread1 and confirm that thread2 acquires.
  unblock_thread1.send(()).unwrap();
  acquired_thread2
    .recv_timeout(Duration::from_secs(5))
    .expect("thread2 didn't acquire.");
}

#[test]
fn drop_while_waiting() {
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
  let mut runtime = tokio::runtime::Runtime::new().unwrap();
  let sema = AsyncSemaphore::new(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();
  let handle3 = sema.clone();

  let (tx_thread1, acquired_thread1) = mpsc::channel();
  let (unblock_thread1, rx_thread1) = mpsc::channel();
  let (tx_inqueue_thread3, queued_thread3) = mpsc::channel();
  let (tx_thread3, acquired_thread3) = mpsc::channel();
  let (unblock_thread3, rx_thread3) = mpsc::channel();
  let (tx_thread2_attempt_1, did_not_acquire_thread2_attempt_1) = mpsc::channel();

  runtime.spawn(handle1.with_acquired(move || {
    // Indicate that we've acquired, and then wait to be signaled to exit.
    tx_thread1.send(()).unwrap();
    rx_thread1.recv().unwrap();
    future::ok::<_, ()>(())
  }));

  // Wait for thread1 to acquire, and then launch thread2.
  acquired_thread1
    .recv_timeout(Duration::from_secs(5))
    .expect("thread1 didn't acquire.");

  // thread2 will wait for a little while, but then drop its PermitFuture to give up on waiting.
  runtime.spawn(future::lazy(move || {
    let permit_future = handle2.acquire();
    let delay_future = Delay::new(Instant::now() + Duration::from_millis(10));
    delay_future
      .select2(permit_future)
      .map(move |raced_result| {
        // We expect to have timed out, because the other Future will not resolve until asked.
        match raced_result {
          future::Either::B(_) => panic!("Expected to time out."),
          future::Either::A(_) => {}
        };
        tx_thread2_attempt_1.send(()).unwrap();
      })
      .map_err(|_| panic!("Permit or duration failed."))
  }));

  runtime.spawn(future::lazy(move || {
    tx_inqueue_thread3.send(()).unwrap();
    handle3.with_acquired(move || {
      // Indicate that we've acquired, and then wait to be signaled to exit.
      tx_thread3.send(()).unwrap();
      rx_thread3.recv().unwrap();
      future::ok::<_, ()>(())
    })
  }));

  queued_thread3
    .recv_timeout(Duration::from_secs(5))
    .expect("thread3 didn't ever queue up.");

  // thread2 should signal that it did not successfully acquire for the first attempt.
  did_not_acquire_thread2_attempt_1
    .recv_timeout(Duration::from_secs(5))
    .expect("thread2 should have failed to acquire by now.");

  // Unblock thread1 and confirm that thread3 acquires.
  unblock_thread1.send(()).unwrap();
  acquired_thread3
    .recv_timeout(Duration::from_secs(5))
    .expect("thread3 didn't acquire.");
  unblock_thread3.send(()).unwrap();
}

#[test]
fn dropped_future_is_removed_from_queue() {
  let mut runtime = tokio::runtime::Runtime::new().unwrap();
  let sema = AsyncSemaphore::new(1);
  let handle1 = sema.clone();
  let handle2 = sema.clone();

  let (tx_thread1, acquired_thread1) = mpsc::channel();
  let (unblock_thread1, rx_thread1) = mpsc::channel();
  let (tx_thread2, acquired_thread2) = mpsc::channel();
  let (unblock_thread2, rx_thread2) = mpsc::channel();

  runtime.spawn(handle1.with_acquired(move || {
    // Indicate that we've acquired, and then wait to be signaled to exit.
    tx_thread1.send(()).unwrap();
    rx_thread1.recv().unwrap();
    future::ok::<_, ()>(())
  }));

  // Wait for thread1 to acquire, and then launch thread2.
  acquired_thread1
    .recv_timeout(Duration::from_secs(5))
    .expect("thread1 didn't acquire.");
  let waiter = handle2.with_acquired(move || future::ok::<_, ()>(()));
  runtime.spawn(future::ok::<_, ()>(()).select(waiter).then(move |res| {
    let mut waiter_fute = match res {
      Ok((_, fute)) => fute,
      Err(_) => panic!("future::ok is infallible"),
    };
    // We explicitly poll the future here because the select call resolves
    // immediately when called on a future::ok result, and the second future
    // is never polled.
    let _waiter_res = waiter_fute.poll();
    tx_thread2.send(()).unwrap();
    rx_thread2.recv().unwrap();
    drop(waiter_fute);
    tx_thread2.send(()).unwrap();
    rx_thread2.recv().unwrap();
    future::ok::<_, ()>(())
  }));
  acquired_thread2
    .recv_timeout(Duration::from_secs(5))
    .expect("thread2 didn't acquire.");
  assert_eq!(1, sema.num_waiters());
  unblock_thread2.send(()).unwrap();
  acquired_thread2
    .recv_timeout(Duration::from_secs(5))
    .expect("thread2 didn't drop future.");
  assert_eq!(0, sema.num_waiters());
  unblock_thread2.send(()).unwrap();
  unblock_thread1.send(()).unwrap();
}
