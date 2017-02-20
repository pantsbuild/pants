// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;
use std::io::{Write, Result};

use sha2::{Sha512Trunc256, Digest};

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct Fingerprint(pub [u8;32]);

impl Fingerprint {
  pub fn from_bytes_unsafe(bytes: &[u8]) -> Fingerprint {
    if bytes.len() != 32 {
      panic!("Input value was not a fingerprint; had length: {}", bytes.len());
    }

    let mut fingerprint = [0;32];
    fingerprint.clone_from_slice(&bytes[0..32]);
    Fingerprint(fingerprint)
  }

  pub fn to_hex(&self) -> String {
    let mut s = String::new();
    for &byte in self.0.iter() {
      fmt::Write::write_fmt(&mut s, format_args!("{:x}", byte)).unwrap();
    }
    s
  }
}

/**
 * A Write instance that fingerprints all data that passes through it.
 */
pub struct WriterHasher<W: Write> {
  // Faster on 64 bit platforms than the 256 bit output algorithm.
  hasher: Sha512Trunc256,
  inner: W,
}

impl<W: Write> WriterHasher<W> {
  pub fn new(inner: W) -> WriterHasher<W> {
    WriterHasher {
      hasher: Sha512Trunc256::new(),
      inner: inner,
    }
  }

  /**
   * Returns the result of fingerprinting this stream, and Drops the stream.
   */
  pub fn finish(self) -> Fingerprint {
    Fingerprint::from_bytes_unsafe(&self.hasher.result())
  }
}

impl<W: Write> Write for WriterHasher<W> {
  fn write(&mut self, buf: &[u8]) -> Result<usize> {
    let written = self.inner.write(buf)?;
    // Hash the bytes that were successfully written.
    self.hasher.input(&buf[0..written]);
    Ok(written)
  }

  fn flush(&mut self) -> Result<()> {
    self.inner.flush()
  }
}
