// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::prost::Message;
use bytes::{Bytes, BytesMut};

/// Extension methods on `prost::Message`.
pub trait MessageExt: Message
where
  Self: Sized,
{
  /// Serialize this protobuf message to `bytes::Bytes`.
  fn to_bytes(&self) -> Bytes {
    let mut buf = BytesMut::with_capacity(self.encoded_len());
    self
      .encode(&mut buf)
      .expect("illegal state: encoded_len returned wrong length");
    buf.freeze()
  }
}

impl<M: ::prost::Message> MessageExt for M {}
