// This file provides backward-compatibility for the deprecated BoxFuture type from futures.
// https://github.com/alexcrichton/futures-rs/issues/228 has background for its removal.
// This avoids needing to call Box::new() around every future that we produce.

extern crate futures;

use futures::future::Future;

pub type BoxFuture<T, E> = Box<Future<Item = T, Error = E> + Send>;

pub trait Boxable {
  fn to_boxed(self) -> Box<Self>;
}

impl<F, T, E> Boxable for F
where
  F: Future<Item = T, Error = E> + Send,
{
  fn to_boxed(self) -> Box<Self>
  where
    Self: Sized,
  {
    Box::new(self)
  }
}
