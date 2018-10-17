// This file provides backward-compatibility for the deprecated BoxFuture type from futures.
// https://github.com/alexcrichton/futures-rs/issues/228 has background for its removal.
// This avoids needing to call Box::new() around every future that we produce.

// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![cfg_attr(
  feature = "cargo-clippy",
  deny(
    clippy,
    default_trait_access,
    expl_impl_clone_on_copy,
    if_not_else,
    needless_continue,
    single_match_else,
    unseparated_literal_suffix,
    used_underscore_binding
  )
)]
// It is often more clear to show that nothing is being moved.
#![cfg_attr(feature = "cargo-clippy", allow(match_ref_pats))]
// Subjective style.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(len_without_is_empty, redundant_field_names)
)]
// Default isn't as big a deal as people seem to think it is.
#![cfg_attr(
  feature = "cargo-clippy",
  allow(new_without_default, new_without_default_derive)
)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![cfg_attr(feature = "cargo-clippy", allow(mutex_atomic))]

extern crate futures;

use futures::future::Future;

pub type BoxFuture<T, E> = Box<Future<Item = T, Error = E> + Send>;

pub trait Boxable<T, E> {
  fn to_boxed(self) -> BoxFuture<T, E>;
}

impl<F, T, E> Boxable<T, E> for F
where
  F: Future<Item = T, Error = E> + Send + 'static,
{
  fn to_boxed(self) -> BoxFuture<T, E>
  where
    Self: Sized,
  {
    Box::new(self)
  }
}

///
/// Just like try! (or the ? operator) but which early-returns a Box<FutureResult<Err>> instead of
/// an Err.
///
#[macro_export]
macro_rules! try_future {
  ($x:expr) => {{
    match $x {
      Ok(value) => value,
      Err(error) => {
        use futures::future::err;
        return err(error).to_boxed();
      }
    }
  }};
}
