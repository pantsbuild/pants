
# async-await port notes

Many functions at the boundary between ported async-await, stdlib futures code and legacy
future 0.1 code temporarily return futures 0.3 BoxFuture and use explicit lifetimes, because that
is easier for a futures 0.1 consumer. stdlib futures consumers can easily call async functions with
references (because they can remain "on the stack"), but an 0.1 future cannot. These methods can be
swapped back to async once all callers are using async-await.

