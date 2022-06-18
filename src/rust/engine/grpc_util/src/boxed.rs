use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use tower::ServiceExt;
use tower_layer::{layer_fn, LayerFn};
use tower_service::Service;

pub struct BoxServiceSync<T, U, E> {
  inner: Box<
    dyn Service<T, Response = U, Error = E, Future = BoxFutureSync<U, E>> + Send + Sync + 'static,
  >,
}

type BoxFutureSync<T, E> = Pin<Box<dyn Future<Output = Result<T, E>> + Send + Sync + 'static>>;

impl<T, U, E> BoxServiceSync<T, U, E> {
  pub fn new<S>(inner: S) -> Self
  where
    S: Service<T, Response = U, Error = E> + Send + Sync + 'static,
    S::Future: Send + Sync + 'static,
  {
    let inner = Box::new(inner.map_future(|f: S::Future| Box::pin(f) as _));
    BoxServiceSync { inner }
  }

  /// Returns a [`Layer`] for wrapping a [`Service`] in a [`BoxServiceSync`]
  /// middleware.
  ///
  /// [`Layer`]: crate::Layer
  pub fn layer<S>() -> LayerFn<fn(S) -> Self>
  where
    S: Service<T, Response = U, Error = E> + Send + Sync + 'static,
    S::Future: Send + Sync + 'static,
  {
    layer_fn(Self::new)
  }
}

impl<T, U, E> Service<T> for BoxServiceSync<T, U, E> {
  type Response = U;
  type Error = E;
  type Future = futures::future::BoxFuture<'static, Result<Self::Response, Self::Error>>;

  fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), E>> {
    self.inner.poll_ready(cx)
  }

  fn call(&mut self, request: T) -> Self::Future {
    Box::pin(async move {
      self.inner.call(request).await
    })
  }
}

impl<T, U, E> fmt::Debug for BoxServiceSync<T, U, E> {
  fn fmt(&self, fmt: &mut fmt::Formatter) -> fmt::Result {
    fmt.debug_struct("BoxServiceSync").finish()
  }
}
