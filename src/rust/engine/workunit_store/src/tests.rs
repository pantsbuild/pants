use crate::SpanId;

#[test]
fn workunit_span_id_has_16_digits_len_hex_format() {
  let number: u64 = 1;
  let hex_string = SpanId(number).to_string();
  assert_eq!(16, hex_string.len());
  for ch in hex_string.chars() {
    assert!(ch.is_ascii_hexdigit())
  }
}

#[test]
fn hex_16_digit_string_actually_uses_input_number() {
  assert_eq!(
    SpanId(0x_ffff_ffff_ffff_ffff).to_string(),
    "ffffffffffffffff"
  );
  assert_eq!(SpanId(0x_1).to_string(), "0000000000000001");
  assert_eq!(
    SpanId(0x_0123_4567_89ab_cdef).to_string(),
    "0123456789abcdef"
  );
}
