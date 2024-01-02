// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;
use std::task::{Context, Poll};

use http::header::HeaderMap;
use http::Request;
use tower_layer::Layer;
use tower_service::Service;

#[derive(Debug)]
pub struct SetRequestHeadersLayer {
    headers: HeaderMap,
}

impl SetRequestHeadersLayer {
    pub fn new(headers: HeaderMap) -> Self {
        SetRequestHeadersLayer { headers }
    }
}

impl<S> Layer<S> for SetRequestHeadersLayer {
    type Service = SetRequestHeaders<S>;

    fn layer(&self, inner: S) -> Self::Service {
        SetRequestHeaders {
            inner,
            headers: self.headers.clone(),
        }
    }
}

#[derive(Clone)]
pub struct SetRequestHeaders<S> {
    inner: S,
    headers: HeaderMap,
}

impl<S> SetRequestHeaders<S> {
    pub fn new(inner: S, headers: HeaderMap) -> Self {
        SetRequestHeaders { inner, headers }
    }
}

impl<S> fmt::Debug for SetRequestHeaders<S>
where
    S: fmt::Debug,
{
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SetRequestHeaders")
            .field("inner", &self.inner)
            .field("headers", &self.headers)
            .finish()
    }
}

impl<ReqBody, S> Service<Request<ReqBody>> for SetRequestHeaders<S>
where
    S: Service<Request<ReqBody>>,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = S::Future;

    #[inline]
    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, mut req: Request<ReqBody>) -> Self::Future {
        if !self.headers.is_empty() {
            let headers = req.headers_mut();
            for (header_name, header_value) in &self.headers {
                headers.insert(header_name, header_value.clone());
            }
        }

        self.inner.call(req)
    }
}
