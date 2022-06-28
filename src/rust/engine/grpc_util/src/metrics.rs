// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::fmt;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use futures::ready;
use futures::Future;
use http::{Request, Response};
use pin_project::pin_project;
use tower_layer::Layer;
use tower_service::Service;
use workunit_store::{get_workunit_store_handle, ObservationMetric};

#[derive(Clone, Debug)]
pub struct NetworkMetricsLayer {
  metric_for_path: Arc<HashMap<String, ObservationMetric>>,
}

impl<S> Layer<S> for NetworkMetricsLayer {
  type Service = NetworkMetrics<S>;

  fn layer(&self, inner: S) -> Self::Service {
    NetworkMetrics::new(inner, self.metric_for_path.clone())
  }
}

impl NetworkMetricsLayer {
  pub fn new(metric_for_path: &Arc<HashMap<String, ObservationMetric>>) -> Self {
    Self {
      metric_for_path: Arc::clone(metric_for_path),
    }
  }
}

pub struct NetworkMetrics<S> {
  inner: S,
  metric_for_path: Arc<HashMap<String, ObservationMetric>>,
}

impl<S> NetworkMetrics<S> {
  pub fn new(inner: S, metric_for_path: Arc<HashMap<String, ObservationMetric>>) -> Self {
    Self {
      inner,
      metric_for_path,
    }
  }
}

impl<S> fmt::Debug for NetworkMetrics<S>
where
  S: fmt::Debug,
{
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    f.debug_struct("NetworkMetrics")
      .field("inner", &self.inner)
      .finish()
  }
}

#[pin_project]
pub struct NetworkMetricsFuture<F> {
  #[pin]
  inner: F,
  metric_data: Option<(ObservationMetric, Instant)>,
}

impl<F, B, E> Future for NetworkMetricsFuture<F>
where
  F: Future<Output = Result<Response<B>, E>>,
{
  type Output = Result<Response<B>, E>;

  fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
    let metric_data = self.metric_data;
    let this = self.project();
    let result = ready!(this.inner.poll(cx));
    if let Some((metric, start)) = metric_data {
      let workunit_store_handle = get_workunit_store_handle();
      if let Some(workunit_store_handle) = workunit_store_handle {
        workunit_store_handle
          .store
          .record_observation(metric, start.elapsed().as_micros() as u64)
      }
    }
    Poll::Ready(result)
  }
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for NetworkMetrics<S>
where
  S: Service<Request<ReqBody>, Response = Response<ResBody>>,
{
  type Response = S::Response;
  type Error = S::Error;
  type Future = NetworkMetricsFuture<S::Future>;

  #[inline]
  fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
    self.inner.poll_ready(cx)
  }

  fn call(&mut self, req: Request<ReqBody>) -> Self::Future {
    let metric_data = self
      .metric_for_path
      .get(req.uri().path())
      .cloned()
      .map(|metric| (metric, Instant::now()));
    NetworkMetricsFuture {
      inner: self.inner.call(req),
      metric_data,
    }
  }
}
