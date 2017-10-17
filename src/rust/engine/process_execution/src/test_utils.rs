pub fn owned_string_vec(args: &[&str]) -> Vec<String> {
  args.into_iter().map(|s| s.to_string()).collect()
}

pub fn as_byte_owned_vec(str: &str) -> Vec<u8> {
  Vec::from(str.as_bytes())
}
