// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::collections::{BTreeMap, HashMap};
use std::iter::FromIterator;
use std::str::FromStr;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Duration;

use either::Either;
use futures::future::BoxFuture;
use futures::{FutureExt, TryFutureExt};
use http::header::HeaderName;
use http::{HeaderMap, HeaderValue};
use hyper::Uri;
use itertools::Itertools;
use lazy_static::lazy_static;
use tokio_rustls::rustls::ClientConfig;
use tower::limit::ConcurrencyLimit;
use tower::timeout::{Timeout, TimeoutLayer};
use tower::ServiceBuilder;
use tower_service::Service;
use workunit_store::{get_workunit_store_handle, Metric, ObservationMetric};

use crate::channel::Channel;
use crate::headers::{SetRequestHeaders, SetRequestHeadersLayer};
use crate::metrics::{NetworkMetrics, NetworkMetricsLayer};

pub mod channel;
pub mod headers;
pub mod hyper_util;
pub mod metrics;
pub mod prost;
pub mod retry;
pub mod tls;

// NB: Rather than boxing our tower/tonic services, we define a type alias that fully defines the
// Service layers that we use universally. If this type becomes unwieldy, or our various Services
// diverge in which layers they use, we should instead use a Box<dyn Service<..>>.
pub type LayeredService =
    SetRequestHeaders<ConcurrencyLimit<NetworkMetrics<CountErrorsService<Timeout<Channel>>>>>;

pub fn layered_service(
    channel: Channel,
    concurrency_limit: usize,
    http_headers: HeaderMap,
    timeout: Option<(Duration, Metric)>,
) -> LayeredService {
    let (timeout, metric) = timeout
        .map(|(t, m)| (t, Some(m)))
        .unwrap_or_else(|| (Duration::from_secs(60 * 60), None));

    ServiceBuilder::new()
        .layer(SetRequestHeadersLayer::new(http_headers))
        .concurrency_limit(concurrency_limit)
        .layer(NetworkMetricsLayer::new(&METRIC_FOR_REAPI_PATH))
        .layer_fn(|service| CountErrorsService { service, metric })
        .layer(TimeoutLayer::new(timeout))
        .service(channel)
}

lazy_static! {
    static ref METRIC_FOR_REAPI_PATH: Arc<HashMap<String, ObservationMetric>> = {
        let mut m = HashMap::new();
        m.insert(
            "/build.bazel.remote.execution.v2.ActionCache/GetActionResult".to_string(),
            ObservationMetric::RemoteCacheGetActionResultNetworkTimeMicros,
        );
        Arc::new(m)
    };
}

pub async fn create_channel(
    addr: &str,
    tls_config: Option<&ClientConfig>,
) -> Result<Channel, String> {
    let uri = Uri::try_from(addr).map_err(|err| format!("invalid address: {err}"))?;
    Channel::new(tls_config, uri)
        .await
        .map_err(|err| format!("gRPC connection error: {err}"))
}

pub fn headers_to_http_header_map(headers: &BTreeMap<String, String>) -> Result<HeaderMap, String> {
    let (http_headers, errors): (Vec<(HeaderName, HeaderValue)>, Vec<String>) = headers
        .iter()
        .map(|(key, value)| {
            let header_name = HeaderName::from_str(key)
                .map_err(|err| format!("Invalid header name {key}: {err}"))?;

            let header_value = HeaderValue::from_str(value)
                .map_err(|err| format!("Invalid header value {value}: {err}"))?;

            Ok((header_name, header_value))
        })
        .partition_map(|result| match result {
            Ok(v) => Either::Left(v),
            Err(err) => Either::Right(err),
        });

    if !errors.is_empty() {
        return Err(format!("header conversion errors: {}", errors.join("; ")));
    }

    Ok(HeaderMap::from_iter(http_headers))
}

pub fn status_ref_to_str(status: &tonic::Status) -> String {
    format!("{:?}: {:?}", status.code(), status.message())
}

pub fn status_to_str(status: tonic::Status) -> String {
    status_ref_to_str(&status)
}

#[derive(Clone)]
pub struct CountErrorsService<S> {
    service: S,
    metric: Option<Metric>,
}

impl<S, Request> Service<Request> for CountErrorsService<S>
where
    S: Service<Request> + Send + 'static,
    S::Response: Send + 'static,
    S::Error: Send + 'static,
    S::Future: Send + 'static,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = BoxFuture<'static, Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.service.poll_ready(cx)
    }

    fn call(&mut self, req: Request) -> Self::Future {
        let metric = self.metric;
        let result = self.service.call(req);
        result
            .inspect_err(move |_| {
                if let Some(metric) = metric {
                    if let Some(mut workunit_store_handle) = get_workunit_store_handle() {
                        workunit_store_handle.store.increment_counter(metric, 1)
                    }
                }
            })
            .boxed()
    }
}

#[cfg(test)]
mod tests {
    mod gen {
        tonic::include_proto!("test");
    }

    use std::collections::BTreeMap;

    use async_trait::async_trait;
    use futures::FutureExt;
    use tokio::sync::oneshot;
    use tonic::transport::Server;
    use tonic::{Request, Response, Status};

    use crate::hyper_util::AddrIncomingWithStream;
    use crate::{headers_to_http_header_map, layered_service};

    #[tokio::test]
    async fn user_agent_is_set_correctly() {
        const EXPECTED_USER_AGENT: &str = "testclient/0.0.1";

        #[derive(Clone)]
        struct UserAgentResponder;

        #[async_trait]
        impl gen::test_server::Test for UserAgentResponder {
            async fn call(
                &self,
                request: Request<gen::Input>,
            ) -> Result<Response<gen::Output>, Status> {
                match request.metadata().get("user-agent") {
                    Some(user_agent_value) => {
                        let user_agent = user_agent_value.to_str().map_err(|err| {
                            Status::invalid_argument(format!(
                                "Unable to convert user-agent header to string: {err}"
                            ))
                        })?;
                        if user_agent.contains(EXPECTED_USER_AGENT) {
                            Ok(Response::new(gen::Output {}))
                        } else {
                            Err(Status::invalid_argument(format!(
                "user-agent header did not contain expected value: actual={user_agent}"
              )))
                        }
                    }
                    None => Err(Status::invalid_argument("user-agent header was not set")),
                }
            }
        }

        let addr = "127.0.0.1:0".parse().expect("failed to parse IP address");
        let incoming = hyper::server::conn::AddrIncoming::bind(&addr).expect("failed to bind port");
        let local_addr = incoming.local_addr();
        let incoming = AddrIncomingWithStream(incoming);

        // Setup shutdown signal handler.
        let (_shutdown_sender, shutdown_receiver) = oneshot::channel::<()>();

        tokio::spawn(async move {
            let mut server = Server::builder();
            let router = server.add_service(gen::test_server::TestServer::new(UserAgentResponder));
            router
                .serve_with_incoming_shutdown(incoming, shutdown_receiver.map(drop))
                .await
                .unwrap();
        });

        let headers = {
            let mut h = BTreeMap::new();
            h.insert("user-agent".to_owned(), EXPECTED_USER_AGENT.to_owned());
            h
        };

        let headers = headers_to_http_header_map(&headers).unwrap();

        let channel =
            super::create_channel(&format!("http://127.0.0.1:{}", local_addr.port()), None)
                .await
                .unwrap();

        let client = layered_service(channel, 1, headers, None);

        let mut client = gen::test_client::TestClient::new(client);
        client.call(gen::Input {}).await.expect("success");
    }
}
