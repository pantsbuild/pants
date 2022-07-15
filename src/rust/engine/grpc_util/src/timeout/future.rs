//! Future types

use super::error::Elapsed;
use pin_project_lite::pin_project;
use std::{
  future::Future,
  pin::Pin,
  task::{Context, Poll},
};
use tokio::time::Sleep;
use workunit_store::{get_workunit_store_handle, Metric};

pin_project! {
    /// [`Timeout`] response future
    ///
    /// [`Timeout`]: crate::timeout::Timeout
    #[derive(Debug)]
    pub struct ResponseFuture<T> {
        #[pin]
        response: T,
        #[pin]
        sleep: Sleep,
    }
}

impl<T> ResponseFuture<T> {
  pub(crate) fn new(response: T, sleep: Sleep) -> Self {
    ResponseFuture { response, sleep }
  }
}

impl<F, T, E> Future for ResponseFuture<F>
where
  F: Future<Output = Result<T, E>>,
  E: Into<tower::BoxError>,
{
  type Output = Result<T, tower::BoxError>;

  fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
    let this = self.project();

    // First, try polling the future
    match this.response.poll(cx) {
      Poll::Ready(v) => return Poll::Ready(v.map_err(Into::into)),
      Poll::Pending => {}
    }

    // Now check the sleep
    match this.sleep.poll(cx) {
      Poll::Pending => Poll::Pending,
      Poll::Ready(_) => {
        if let Some(mut workunit_store_handle) = get_workunit_store_handle() {
          workunit_store_handle
            .store
            .increment_counter(Metric::RemoteCacheRequestTimeouts, 1)
        }

        Poll::Ready(Err(Elapsed(()).into()))
      },
    }
  }
}
