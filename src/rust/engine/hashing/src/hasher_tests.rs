#[test]
fn hashes() {
    let mut src = "meep".as_bytes();

    let dst = Vec::with_capacity(10);
    let mut hasher = super::WriterHasher::new(dst);
    assert_eq!(std::io::copy(&mut src, &mut hasher).unwrap(), 4);
    let want = (
        super::Digest::new(
            super::Fingerprint::from_hex_string(
                "23e92dfba8fb0c93cfba31ad2962b4e35a47054296d1d375d7f7e13e0185de7a",
            )
            .unwrap(),
            4,
        ),
        "meep".as_bytes().to_vec(),
    );
    assert_eq!(hasher.finish(), want);
}
