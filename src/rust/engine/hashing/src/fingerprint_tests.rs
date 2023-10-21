// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::Fingerprint;
use serde_test::{assert_ser_tokens, Token};

#[test]
fn from_bytes_unsafe() {
    assert_eq!(
        Fingerprint::from_bytes_unsafe(&[
            0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab,
            0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab, 0xab,
            0xab, 0xab, 0xab, 0xab,
        ],),
        Fingerprint([0xab; 32])
    );
}

#[test]
fn from_hex_string() {
    assert_eq!(
        Fingerprint::from_hex_string(
            "0123456789abcdefFEDCBA98765432100000000000000000ffFFfFfFFfFfFFff",
        )
        .unwrap(),
        Fingerprint([
            0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef, 0xfe, 0xdc, 0xba, 0x98, 0x76, 0x54,
            0x32, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
            0xff, 0xff, 0xff, 0xff,
        ],)
    )
}

#[test]
fn from_hex_string_not_long_enough() {
    Fingerprint::from_hex_string("abcd").expect_err("Want err");
}

#[test]
fn from_hex_string_too_long() {
    Fingerprint::from_hex_string(
        "0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0",
    )
    .expect_err("Want err");
}

#[test]
fn from_hex_string_invalid_chars() {
    Fingerprint::from_hex_string(
        "Q123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF",
    )
    .expect_err("Want err");
}

#[test]
fn to_hex() {
    assert_eq!(
        Fingerprint([
            0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef, 0xfe, 0xdc, 0xba, 0x98, 0x76, 0x54,
            0x32, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff,
            0xff, 0xff, 0xff, 0xff,
        ],)
        .to_hex(),
        "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff".to_lowercase()
    )
}

#[test]
fn display() {
    let hex = "0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF";
    assert_eq!(
        Fingerprint::from_hex_string(hex).unwrap().to_hex(),
        hex.to_lowercase()
    )
}

#[test]
fn serialize_to_str() {
    let fingerprint = Fingerprint([
        0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef, 0xfe, 0xdc, 0xba, 0x98, 0x76, 0x54, 0x32,
        0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0xff, 0xff,
    ]);
    assert_ser_tokens(
        &fingerprint,
        &[Token::Str(
            "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
        )],
    );
}
