
# async-await port notes

stdlib futures consumers can easily call async functions with references (because they can
remain "on the stack"), but using 0.1 futures combinators with async functions is challenging in
the face of references. Rather than using combinators, 0.1 futures callers of stdlib Future/async
functions can wrap their calls in async blocks that capture (via `move`) any state they need to
execute:

    // Box and pin a stdlib future, and then convert it to a futures01 future via `compat()`.
    // The final `to_boxed()` call is necessary for functions that return boxfuture::BoxFuture.
    Box::pin(async move {
      // stdlib futures usage goes here.
    }).compat().to_boxed()

