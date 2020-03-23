use crate::hex_16_digit_string;

#[test]
fn workunit_span_id_has_16_digits_len_hex_format() {
  let number: u64 = 1;
  let hex_string = hex_16_digit_string(number);
  assert_eq!(16, hex_string.len());
  for ch in hex_string.chars() {
    assert!(ch.is_ascii_hexdigit())
  }
}

#[test]
fn hex_16_digit_string_actually_uses_input_number() {
  assert_eq!(
    hex_16_digit_string(0x_ffff_ffff_ffff_ffff),
    "ffffffffffffffff"
  );
  assert_eq!(hex_16_digit_string(0x_1), "0000000000000001");
  assert_eq!(
    hex_16_digit_string(0x_0123_4567_89ab_cdef),
    "0123456789abcdef"
  );
}
