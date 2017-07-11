// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;
use std::io::{Write, Result};

use blake2_rfc::blake2b::Blake2b;

const FINGERPRINT_SIZE: usize = 32;

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct Fingerprint(pub [u8;FINGERPRINT_SIZE]);

impl Fingerprint {
  pub fn from_bytes_unsafe(bytes: &[u8]) -> Fingerprint {
    if bytes.len() != FINGERPRINT_SIZE {
      panic!("Input value was not a fingerprint; had length: {}", bytes.len());
    }

    let mut fingerprint = [0;FINGERPRINT_SIZE];
    fingerprint.clone_from_slice(&bytes[0..FINGERPRINT_SIZE]);
    Fingerprint(fingerprint)
  }

  pub fn to_hex(&self) -> String {
    let mut s = String::new();
    for &byte in self.0.iter() {
      fmt::Write::write_fmt(&mut s, format_args!("{:02x}", byte)).unwrap();
    }
    s
  }
}

///
/// A Write instance that fingerprints all data that passes through it.
///
pub struct WriterHasher<W: Write> {
  hasher: Blake2b,
  inner: W,
}

impl<W: Write> WriterHasher<W> {
  pub fn new(inner: W) -> WriterHasher<W> {
    WriterHasher {
      hasher: Blake2b::new(FINGERPRINT_SIZE),
      inner: inner,
    }
  }

  ///
  /// Returns the result of fingerprinting this stream, and Drops the stream.
  ///
  pub fn finish(self) -> Fingerprint {
    Fingerprint::from_bytes_unsafe(&self.hasher.finalize().as_bytes())
  }
}

impl<W: Write> Write for WriterHasher<W> {
  fn write(&mut self, buf: &[u8]) -> Result<usize> {
    let written = self.inner.write(buf)?;
    // Hash the bytes that were successfully written.
    self.hasher.update(&buf[0..written]);
    Ok(written)
  }

  fn flush(&mut self) -> Result<()> {
    self.inner.flush()
  }
}
