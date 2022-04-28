use crate::nailgun::interpolation_context::InterpolationContext;

#[test]
fn leaves_strings_untouched_when_no_interpolation_syntax_is_present() {
  let orig_str = "My desired string".to_string();

  let mut ctx = InterpolationContext::new();
  ctx.set("desired".to_string(), "undesired".to_string());

  assert_eq!(orig_str, ctx.format(orig_str.clone()))
}

#[test]
fn transform_strings_based_on_context() {
  let orig_str = "My ${interpolated} ${string}, which I ${interpolated}".to_string();

  let mut ctx = InterpolationContext::new();
  ctx.set("interpolated".to_string(), "desired".to_string());
  ctx.set("string".to_string(), "value".to_string());

  assert_eq!(
    "My desired value, which I desired".to_string(),
    ctx.format(orig_str)
  )
}
