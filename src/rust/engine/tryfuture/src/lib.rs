// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

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
