// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
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

use std::fmt;
use std::io::{self, Error, Write};
use std::pin::Pin;
use std::str::FromStr;
use std::task::{Context, Poll};

use byteorder::ByteOrder;
use deepsize::DeepSizeOf;
use digest::consts::U32;
use generic_array::GenericArray;
use serde::de::{MapAccess, Visitor};
use serde::ser::{Serialize, SerializeStruct, Serializer};
use serde::{Deserialize, Deserializer};
use sha2::{Digest as Sha256Digest, Sha256};
use tokio::io::{AsyncRead, AsyncWrite};

pub const EMPTY_FINGERPRINT: Fingerprint = Fingerprint([
    0xe3, 0xb0, 0xc4, 0x42, 0x98, 0xfc, 0x1c, 0x14, 0x9a, 0xfb, 0xf4, 0xc8, 0x99, 0x6f, 0xb9, 0x24,
    0x27, 0xae, 0x41, 0xe4, 0x64, 0x9b, 0x93, 0x4c, 0xa4, 0x95, 0x99, 0x1b, 0x78, 0x52, 0xb8, 0x55,
]);
pub const EMPTY_DIGEST: Digest = Digest {
    hash: EMPTY_FINGERPRINT,
    size_bytes: 0,
};

pub const FINGERPRINT_SIZE: usize = 32;

#[derive(Clone, Copy, DeepSizeOf, Eq, Hash, PartialEq, Ord, PartialOrd)]
pub struct Fingerprint(pub [u8; FINGERPRINT_SIZE]);

impl Fingerprint {
    pub fn from_bytes_unsafe(bytes: &[u8]) -> Fingerprint {
        if bytes.len() != FINGERPRINT_SIZE {
            panic!(
                "Input value was not a fingerprint; had length: {}",
                bytes.len()
            );
        }

        let mut fingerprint = [0; FINGERPRINT_SIZE];
        fingerprint.clone_from_slice(&bytes[0..FINGERPRINT_SIZE]);
        Fingerprint(fingerprint)
    }

    pub fn from_bytes(bytes: GenericArray<u8, U32>) -> Fingerprint {
        Fingerprint(bytes.into())
    }

    pub fn from_hex_string(hex_string: &str) -> Result<Fingerprint, String> {
        <[u8; FINGERPRINT_SIZE] as hex::FromHex>::from_hex(hex_string)
            .map(Fingerprint)
            .map_err(|e| format!("{e:?}"))
    }

    pub fn as_bytes(&self) -> &[u8; FINGERPRINT_SIZE] {
        &self.0
    }

    #[allow(clippy::wrong_self_convention)]
    pub fn to_hex(&self) -> String {
        let mut s = String::new();
        for &byte in &self.0 {
            fmt::Write::write_fmt(&mut s, format_args!("{byte:02x}")).unwrap();
        }
        s
    }

    ///
    /// Using the fact that a Fingerprint is computed using a strong hash function, computes a strong
    /// but short hash value from a prefix.
    ///
    pub fn prefix_hash(&self) -> u64 {
        byteorder::BigEndian::read_u64(&self.0)
    }
}

impl fmt::Display for Fingerprint {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_hex())
    }
}

impl fmt::Debug for Fingerprint {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Fingerprint<{}>", self.to_hex())
    }
}

impl AsRef<[u8]> for Fingerprint {
    fn as_ref(&self) -> &[u8] {
        &self.0[..]
    }
}

impl Serialize for Fingerprint {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.to_hex().as_str())
    }
}

impl<'de> Deserialize<'de> for Fingerprint {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct FingerprintVisitor;

        impl<'de> Visitor<'de> for FingerprintVisitor {
            type Value = Fingerprint;

            fn expecting(&self, formatter: &mut fmt::Formatter) -> Result<(), fmt::Error> {
                formatter.write_str("struct Fingerprint")
            }

            fn visit_str<E>(self, v: &str) -> Result<Self::Value, E>
            where
                E: serde::de::Error,
            {
                Fingerprint::from_hex_string(v).map_err(|err| {
                    serde::de::Error::invalid_value(
                        serde::de::Unexpected::Str(&format!("{v:?}: {err}")),
                        &format!("A hex representation of a {FINGERPRINT_SIZE} byte value")
                            .as_str(),
                    )
                })
            }
        }

        deserializer.deserialize_string(FingerprintVisitor)
    }
}

impl FromStr for Fingerprint {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Fingerprint::from_hex_string(s)
    }
}

impl TryFrom<&str> for Fingerprint {
    type Error = String;

    fn try_from(s: &str) -> Result<Self, Self::Error> {
        Fingerprint::from_hex_string(s)
    }
}

///
/// A Digest is a fingerprint, as well as the size in bytes of the plaintext for which that is the
/// fingerprint.
///
/// It is equivalent to a Bazel Remote Execution Digest, but without the overhead (and awkward API)
/// of needing to create an entire protobuf to pass around the two fields.
///
#[derive(Clone, Copy, Debug, DeepSizeOf, Eq, Hash, PartialEq)]
pub struct Digest {
    pub hash: Fingerprint,
    pub size_bytes: usize,
}

impl Serialize for Digest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut obj = serializer.serialize_struct("digest", 2)?;
        obj.serialize_field("fingerprint", &self.hash)?;
        obj.serialize_field("size_bytes", &self.size_bytes)?;
        obj.end()
    }
}

#[derive(Deserialize)]
#[serde(field_identifier, rename_all = "snake_case")]
enum Field {
    Fingerprint,
    SizeBytes,
}

impl<'de> Deserialize<'de> for Digest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct DigestVisitor;

        impl<'de> Visitor<'de> for DigestVisitor {
            type Value = Digest;

            fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
                formatter.write_str("struct digest")
            }

            fn visit_map<V>(self, mut map: V) -> Result<Digest, V::Error>
            where
                V: MapAccess<'de>,
            {
                use serde::de;

                let mut fingerprint = None;
                let mut size_bytes = None;
                while let Some(key) = map.next_key()? {
                    match key {
                        Field::Fingerprint => {
                            if fingerprint.is_some() {
                                return Err(de::Error::duplicate_field("fingerprint"));
                            }
                            fingerprint = Some(map.next_value()?);
                        }
                        Field::SizeBytes => {
                            if size_bytes.is_some() {
                                return Err(de::Error::duplicate_field("size_bytes"));
                            }
                            size_bytes = Some(map.next_value()?);
                        }
                    }
                }
                let fingerprint =
                    fingerprint.ok_or_else(|| de::Error::missing_field("fingerprint"))?;
                let size_bytes =
                    size_bytes.ok_or_else(|| de::Error::missing_field("size_bytes"))?;
                Ok(Digest::new(fingerprint, size_bytes))
            }
        }

        const FIELDS: &[&str] = &["fingerprint", "size_bytes"];
        deserializer.deserialize_struct("digest", FIELDS, DigestVisitor)
    }
}

impl Digest {
    pub fn new(hash: Fingerprint, size_bytes: usize) -> Digest {
        Digest { hash, size_bytes }
    }

    pub fn of_bytes(bytes: &[u8]) -> Self {
        let mut hasher = Sha256::default();
        hasher.update(bytes);

        Digest::new(Fingerprint::from_bytes(hasher.finalize()), bytes.len())
    }
}

///
/// A Write instance that fingerprints all data that passes through it.
///
pub struct WriterHasher<T> {
    hasher: Sha256,
    byte_count: usize,
    inner: T,
}

impl<T> WriterHasher<T> {
    pub fn new(inner: T) -> WriterHasher<T> {
        WriterHasher {
            hasher: Sha256::default(),
            byte_count: 0,
            inner: inner,
        }
    }

    ///
    /// Returns the result of fingerprinting this stream, and Drops the stream.
    ///
    pub fn finish(self) -> (Digest, T) {
        (
            Digest::new(
                Fingerprint::from_bytes(self.hasher.finalize()),
                self.byte_count,
            ),
            self.inner,
        )
    }
}

impl<W: Write> Write for WriterHasher<W> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let written = self.inner.write(buf)?;
        // Hash the bytes that were successfully written.
        self.hasher.update(&buf[0..written]);
        self.byte_count += written;
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

impl<AW: ?Sized + AsyncWrite + Unpin> AsyncWrite for WriterHasher<&mut AW> {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<Result<usize, Error>> {
        let inner = Pin::new(&mut *self.inner);
        let result = inner.poll_write(cx, buf);
        if let Poll::Ready(Ok(written)) = result {
            // Hash the bytes that were successfully written.
            self.hasher.update(&buf[0..written]);
            self.byte_count += written;
        }
        result
    }

    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Result<(), Error>> {
        let inner = Pin::new(&mut *self.inner);
        inner.poll_flush(cx)
    }

    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Result<(), Error>> {
        let inner = Pin::new(&mut *self.inner);
        inner.poll_shutdown(cx)
    }
}

///
/// Copy the data from reader and hash the bytes in one pass.
/// Use hash() to just hash without copying the data anywhere.
///
pub fn sync_copy_and_hash<R: ?Sized, W: ?Sized>(
    reader: &mut R,
    writer: &mut W,
) -> io::Result<Digest>
where
    R: io::Read,
    W: io::Write,
{
    let mut hasher = WriterHasher::new(writer);
    let _ = io::copy(reader, &mut hasher)?;
    Ok(hasher.finish().0)
}

///
/// Copy from reader to writer and return whether the copied data matches expected_digest.
///
pub fn sync_verified_copy<R: ?Sized, W: ?Sized>(
    expected_digest: Digest,
    data_is_immutable: bool,
    reader: &mut R,
    writer: &mut W,
) -> io::Result<bool>
where
    R: io::Read,
    W: io::Write,
{
    if data_is_immutable {
        // Trust that the data hasn't changed, and only validate its length.
        let copied = io::copy(reader, writer)?;
        Ok(copied as usize == expected_digest.size_bytes)
    } else {
        Ok(expected_digest == sync_copy_and_hash(reader, writer)?)
    }
}

///
/// Copy the data from reader and hash the bytes in one pass.
/// Use hash() to just hash without copying the data anywhere.
///
pub async fn async_copy_and_hash<R, W>(reader: &mut R, writer: &mut W) -> tokio::io::Result<Digest>
where
    R: AsyncRead + Unpin + ?Sized,
    W: AsyncWrite + Unpin + ?Sized,
{
    let mut hasher = WriterHasher::new(writer);
    let _ = tokio::io::copy(reader, &mut hasher).await?;
    Ok(hasher.finish().0)
}

///
/// Copy from reader to writer and return whether the copied data matches expected_digest.
///
pub async fn async_verified_copy<R, W>(
    expected_digest: Digest,
    data_is_immutable: bool,
    reader: &mut R,
    writer: &mut W,
) -> tokio::io::Result<bool>
where
    R: AsyncRead + Unpin + ?Sized,
    W: AsyncWrite + Unpin + ?Sized,
{
    if data_is_immutable {
        // Trust that the data hasn't changed, and only validate its length.
        let copied = tokio::io::copy(reader, writer).await?;
        Ok(copied as usize == expected_digest.size_bytes)
    } else {
        Ok(expected_digest == async_copy_and_hash(reader, writer).await?)
    }
}

#[cfg(test)]
mod fingerprint_tests;

#[cfg(test)]
mod digest_tests;

#[cfg(test)]
mod hasher_tests;
