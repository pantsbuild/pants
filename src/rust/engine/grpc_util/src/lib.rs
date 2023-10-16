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

use std::collections::btree_map::Entry;
use std::collections::{BTreeMap, HashMap};
use std::iter::FromIterator;
use std::str::FromStr;
use std::sync::Arc;

use either::Either;
use http::header::{HeaderName, USER_AGENT};
use http::{HeaderMap, HeaderValue};
use itertools::Itertools;
use lazy_static::lazy_static;
use tokio_rustls::rustls::ClientConfig;
use tonic::transport::{Channel, ClientTlsConfig, Endpoint};
use tower::limit::ConcurrencyLimit;
use tower::ServiceBuilder;
use workunit_store::ObservationMetric;

use crate::headers::{SetRequestHeaders, SetRequestHeadersLayer};
use crate::metrics::{NetworkMetrics, NetworkMetricsLayer};

pub mod headers;
pub mod hyper;
pub mod metrics;
pub mod prost;
pub mod retry;
pub mod tls;

// NB: Rather than boxing our tower/tonic services, we define a type alias that fully defines the
// Service layers that we use universally. If this type becomes unwieldy, or our various Services
// diverge in which layers they use, we should instead use a Box<dyn Service<..>>.
pub type LayeredService = SetRequestHeaders<ConcurrencyLimit<NetworkMetrics<Channel>>>;

pub fn layered_service(
    channel: Channel,
    concurrency_limit: usize,
    http_headers: HeaderMap,
) -> LayeredService {
    ServiceBuilder::new()
        .layer(SetRequestHeadersLayer::new(http_headers))
        .concurrency_limit(concurrency_limit)
        .layer(NetworkMetricsLayer::new(&METRIC_FOR_REAPI_PATH))
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

/// Create a Tonic `Endpoint` from a string containing a schema and IP address/name.
pub fn create_endpoint(
    addr: &str,
    tls_config_opt: Option<&ClientConfig>,
    headers: &mut BTreeMap<String, String>,
) -> Result<Endpoint, String> {
    let uri =
        tonic::transport::Uri::try_from(addr).map_err(|err| format!("invalid address: {}", err))?;
    let endpoint = Channel::builder(uri);

    let endpoint = if let Some(tls_config) = tls_config_opt {
        endpoint
            .tls_config(ClientTlsConfig::new().rustls_client_config(tls_config.clone()))
            .map_err(|e| format!("TLS setup error: {}", e))?
    } else {
        endpoint
    };

    let endpoint = match headers.entry(USER_AGENT.as_str().to_owned()) {
        Entry::Occupied(e) => {
            let (_, user_agent) = e.remove_entry();
            endpoint
                .user_agent(user_agent)
                .map_err(|e| format!("Unable to convert user-agent header: {}", e))?
        }
        Entry::Vacant(_) => endpoint,
    };

    Ok(endpoint)
}

pub fn headers_to_http_header_map(headers: &BTreeMap<String, String>) -> Result<HeaderMap, String> {
    let (http_headers, errors): (Vec<(HeaderName, HeaderValue)>, Vec<String>) = headers
        .iter()
        .map(|(key, value)| {
            let header_name = HeaderName::from_str(key)
                .map_err(|err| format!("Invalid header name {}: {}", key, err))?;

            let header_value = HeaderValue::from_str(value)
                .map_err(|err| format!("Invalid header value {}: {}", value, err))?;

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

pub fn status_to_str(status: tonic::Status) -> String {
    format!("{:?}: {:?}", status.code(), status.message())
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
    use tonic::transport::{Channel, Server};
    use tonic::{Request, Response, Status};

    use crate::hyper::AddrIncomingWithStream;

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
                                "Unable to convert user-agent header to string: {}",
                                err
                            ))
                        })?;
                        if user_agent.contains(EXPECTED_USER_AGENT) {
                            Ok(Response::new(gen::Output {}))
                        } else {
                            Err(Status::invalid_argument(format!(
                                "user-agent header did not contain expected value: actual={}",
                                user_agent
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

        let mut headers = {
            let mut h = BTreeMap::new();
            h.insert("user-agent".to_owned(), EXPECTED_USER_AGENT.to_owned());
            h
        };

        let endpoint = super::create_endpoint(
            &format!("grpc://127.0.0.1:{}", local_addr.port()),
            None,
            &mut headers,
        )
        .unwrap();

        let channel = Channel::balance_list(vec![endpoint].into_iter());

        let mut client = gen::test_client::TestClient::new(channel);
        if let Err(err) = client.call(gen::Input {}).await {
            panic!("test failed: {}", err.message());
        }
    }
}
