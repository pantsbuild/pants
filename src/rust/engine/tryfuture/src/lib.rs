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

// Re-export the `futures` crate here so that the `try_future!` macro may safely refer to
// the `futures` crate without regard to how call sites may have imported it.
#[allow(unused_imports)]
pub use futures as __futures_reexport;

///
/// Just like try! (or the ? operator) but early-returns with the any `Result::Err` boxed into
/// a `futures::future::BoxFuture` instead of just an `Err`. The value of `Ok` variants are
/// unwrapped and returned to the caller.
///
#[macro_export]
macro_rules! try_future {
    ($x:expr) => {{
        match $x {
            Ok(value) => value,
            Err(error) => {
                return $crate::__futures_reexport::future::err(error.into()).boxed();
            }
        }
    }};
}

#[cfg(test)]
mod tests {
    use futures::future::{self, BoxFuture};
    use futures::FutureExt;

    fn returns_normally(
        result: Result<&'static str, &'static str>,
    ) -> BoxFuture<'static, Result<&'static str, &'static str>> {
        let value = try_future!(result);
        future::ready(Ok(value)).boxed()
    }

    fn constant_error_if_ok(
        result: Result<&'static str, &'static str>,
    ) -> BoxFuture<'static, Result<&'static str, &'static str>> {
        let _ = try_future!(result);
        future::ready(Err("xyzzy")).boxed()
    }

    #[test]
    fn test_try_future() {
        assert_eq!(
            returns_normally(Ok("hello")).now_or_never(),
            Some(Ok("hello"))
        );
        assert_eq!(
            returns_normally(Err("world")).now_or_never(),
            Some(Err("world"))
        );
        assert_eq!(
            constant_error_if_ok(Ok("hello")).now_or_never(),
            Some(Err("xyzzy"))
        );
        assert_eq!(
            constant_error_if_ok(Err("world")).now_or_never(),
            Some(Err("world"))
        );
    }
}
