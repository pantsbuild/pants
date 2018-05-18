extern crate futures;

use std::sync::{Arc, Mutex};
use std::collections::VecDeque;

use futures::{Async, Poll};
use futures::future::Future;
use futures::task::{self, Task};

struct Inner {
  waiters: VecDeque<Task>,
  available_permits: usize,
}

#[derive(Clone)]
pub struct AsyncSemaphore {
  inner: Arc<Mutex<Inner>>,
}

impl AsyncSemaphore {
  pub fn new(permits: usize) -> AsyncSemaphore {
    AsyncSemaphore {
      inner: Arc::new(Mutex::new(Inner {
        waiters: VecDeque::new(),
        available_permits: permits,
      })),
    }
  }

  ///
  /// Returns a Future that resolves to a Permit for the semaphore. The semaphore remains acquired
  /// until the Permit is dropped.
  ///
  /// You should generally prefer to use `with_acquired`, as it is less error prone.
  ///
  fn acquire(&self) -> PermitFuture {
    PermitFuture {
      inner: Some(self.inner.clone()),
    }
  }

  ///
  /// Runs the given Future-creating function (and the Future it returns) under the semaphore.
  ///
  pub fn with_acquired<F, B, T, E>(&self, f: F) -> Box<Future<Item = T, Error = E> + Send>
  where
    F: FnOnce() -> B + Send + 'static,
    B: Future<Item = T, Error = E> + Send + 'static,
  {
    Box::new(
      self
        .acquire()
        .map_err(|()| panic!("Acquisition is infalliable."))
        .and_then(|permit| {
          f().map(move |t| {
            drop(permit);
            t
          })
        }),
    )
  }
}

pub struct Permit {
  inner: Arc<Mutex<Inner>>,
}

impl Drop for Permit {
  fn drop(&mut self) {
    let task = {
      let mut inner = self.inner.lock().unwrap();
      inner.available_permits += 1;
      if let Some(task) = inner.waiters.pop_front() {
        task
      } else {
        return;
      }
    };
    task.notify();
  }
}

pub struct PermitFuture {
  inner: Option<Arc<Mutex<Inner>>>,
}

impl Future for PermitFuture {
  type Item = Permit;
  type Error = ();

  fn poll(&mut self) -> Poll<Permit, ()> {
    let inner = self.inner.take().expect("cannot poll PermitFuture twice");
    let acquired = {
      let mut inner = inner.lock().unwrap();
      if inner.available_permits == 0 {
        inner.waiters.push_back(task::current());
        false
      } else {
        inner.available_permits -= 1;
        true
      }
    };
    if acquired {
      Ok(Async::Ready(Permit { inner }))
    } else {
      self.inner = Some(inner);
      Ok(Async::NotReady)
    }
  }
}

#[cfg(test)]
mod tests {

  use super::AsyncSemaphore;
  use futures::{future, Future};
  use std::sync::mpsc;
  use std::thread;
  use std::time::Duration;

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
    match acquired_thread2.recv_timeout(Duration::from_millis(500)) {
      Err(_) => (),
      Ok(_) => panic!("thread2 should not have acquired while thread1 was holding."),
    }

    // Unblock thread1 and confirm that thread2 acquires.
    unblock_thread1.send(()).unwrap();
    acquired_thread2
      .recv_timeout(Duration::from_secs(5))
      .expect("thread2 didn't acquire.");
  }
}
