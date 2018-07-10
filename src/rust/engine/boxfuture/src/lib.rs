// This file provides backward-compatibility for the deprecated BoxFuture type from futures.
// https://github.com/alexcrichton/futures-rs/issues/228 has background for its removal.
// This avoids needing to call Box::new() around every future that we produce.

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
        return future::err(error).to_boxed();
      }
    }
  }};
}

///
/// A trait alias specifically for _avoiding_ `BoxFuture` via `impl IFuture`.
///
#[cfg_attr(rustfmt, rustfmt_skip)]
pub trait IFuture<T, E>: Future<Item=T, Error=E> {}
#[cfg_attr(rustfmt, rustfmt_skip)]
impl<T, E, I> IFuture<T, E> for I where I: Future<Item=T, Error=E> {}
