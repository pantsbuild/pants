// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::ops::Deref;
use std::pin::Pin;
use std::task::{Context, Poll};

use futures::Stream;
use hyper::server::accept::Accept;
use hyper::server::conn::{AddrIncoming, AddrStream};

pub struct AddrIncomingWithStream(pub AddrIncoming);

impl Deref for AddrIncomingWithStream {
  type Target = AddrIncoming;

  fn deref(&self) -> &Self::Target {
    &self.0
  }
}

impl Stream for AddrIncomingWithStream {
  type Item = Result<AddrStream, std::io::Error>;

  fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
    Pin::new(&mut self.0).poll_accept(cx)
  }
}
