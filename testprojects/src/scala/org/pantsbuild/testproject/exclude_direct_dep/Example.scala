package org.pantsbuild.testproject.exclude_direct_dep

import com.google.common.base.Preconditions

object Example {
  def main(args: Array[String]) {
    Preconditions.checkNotNull("This is not null.")
  }
}
