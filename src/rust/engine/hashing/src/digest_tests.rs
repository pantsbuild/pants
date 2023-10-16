use self::serde_test::{assert_tokens, Token};
use super::Digest;
use super::Fingerprint;
use serde_test;

#[test]
fn serialize_and_deserialize() {
    let digest = Digest::new(
        Fingerprint::from_hex_string(
            "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
        )
        .unwrap(),
        1,
    );
    assert_tokens(
        &digest,
        &[
            Token::Struct {
                name: "digest",
                len: 2,
            },
            Token::Str("fingerprint"),
            Token::Str("0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff"),
            Token::Str("size_bytes"),
            Token::U64(1),
            Token::StructEnd,
        ],
    );
}
