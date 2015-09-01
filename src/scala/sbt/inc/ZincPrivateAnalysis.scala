// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package sbt.inc

/**
 * TODO: A temporary class in the `sbt.inc` package to deal with the fact that
 * `Analysis.empty` is accidentally package-protected in sbt 0.13.9. Remove after:
 *   https://github.com/sbt/sbt/issues/2159
 */
@deprecated("Temporary class used to work around an accidentally package-protected method.", "0.13.9")
object ZincPrivateAnalysis {
  def empty(nameHashing: Boolean): Analysis = Analysis.empty(nameHashing)
}
