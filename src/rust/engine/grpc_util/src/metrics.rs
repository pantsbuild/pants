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
use workunit_store::{record_observation_if_in_workunit, ObservationMetric};

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

#[derive(Clone)]
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
    F: Future<Output = Result<Response<B>, E>> + Send + 'static,
{
    type Output = Result<Response<B>, E>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let metric_data = self.metric_data;
        let this = self.project();
        let result = ready!(this.inner.poll(cx));
        if let Some((metric, start)) = metric_data {
            record_observation_if_in_workunit(metric, start.elapsed().as_micros() as u64)
        }
        Poll::Ready(result)
    }
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for NetworkMetrics<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>> + Send + 'static,
    ReqBody: Send + 'static,
    ResBody: Send + 'static,
    S::Response: Send + 'static,
    S::Error: Send + 'static,
    S::Future: Send + 'static,
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

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::convert::Infallible;
    use std::sync::Arc;

    use hyper::{Body, Request, Response};
    use tower::{ServiceBuilder, ServiceExt};
    use workunit_store::{Level, ObservationMetric, WorkunitStore};

    use super::NetworkMetricsLayer;

    async fn handler(_: Request<Body>) -> Result<Response<Body>, Infallible> {
        Ok(Response::new(Body::empty()))
    }

    #[tokio::test]
    async fn collects_network_metrics() {
        let ws = WorkunitStore::new(true, Level::Debug);
        ws.init_thread_state(None);

        let metric_for_path: Arc<HashMap<String, ObservationMetric>> = {
            let mut m = HashMap::new();
            m.insert(
                "/this-is-a-metric-path".to_string(),
                ObservationMetric::TestObservation,
            );
            Arc::new(m)
        };

        let svc = ServiceBuilder::new()
            .layer(NetworkMetricsLayer::new(&metric_for_path))
            .service_fn(handler);

        let req = Request::builder()
            .uri("/not-a-metric-path")
            .body(Body::empty())
            .unwrap();

        let _ = svc.clone().oneshot(req).await.unwrap();
        let observations = ws.encode_observations().unwrap();
        assert_eq!(observations.len(), 0); // there should be no observations for `/not-a-metric-path`

        let req = Request::builder()
            .uri("/this-is-a-metric-path")
            .body(Body::empty())
            .unwrap();

        let _ = svc.clone().oneshot(req).await.unwrap();
        let observations = ws.encode_observations().unwrap();
        assert_eq!(observations.len(), 1); // there should be an observation for `/this-is-a-metric-path`
        assert_eq!(
            observations.into_keys().collect::<Vec<_>>(),
            vec!["test_observation"]
        );
    }
}
