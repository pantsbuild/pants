/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.analysis

import java.io.File

/**
 * Configuration for sbt analysis and analysis output options.
 */
case class AnalysisOptions(
  _cache: Option[File]         = None,
  cacheMap: Map[File, File]    = Map.empty,
  rebaseMap: Map[File, File]   = Map.empty,
  clearInvalid: Boolean        = true
) {
  lazy val cache: File =
    _cache.getOrElse {
      throw new RuntimeException(s"An analysis cache file is required.")
    }
}
