# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Adapted from https://mypyc.readthedocs.io/en/latest/getting_started.html#example-program

import time


def fib(n: int) -> int:
    if n <= 1:
        return n
    else:
        return fib(n - 2) + fib(n - 1)


t0 = time.time()
fib(32)
if "__file__" in locals():
    print("interpreted")
else:
    print("compiled")
print(time.time() - t0)
