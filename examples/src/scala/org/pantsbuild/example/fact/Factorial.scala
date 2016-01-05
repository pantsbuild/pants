// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.example.fact

import scala.annotation.tailrec

/** A scala implementation of factorial, with no dependencies. */
object Factorial {
  @tailrec
  def apply(n: BigInt, result: BigInt = 1): BigInt =
    if (n == 0) result else apply(n-1, n * result)
}
