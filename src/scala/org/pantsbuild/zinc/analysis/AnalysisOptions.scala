/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.analysis

import java.io.File
import org.pantsbuild.zinc.util.Util

/**
 * Configuration for sbt analysis and analysis output options.
 */
case class AnalysisOptions(
  _cache: Option[File]         = None,
  cacheMap: Map[File, File]    = Map.empty,
  rebaseMap: Map[File, File]   = Map(new File(System.getProperty("user.dir")) -> new File("/proc/self/cwd")),
  clearInvalid: Boolean        = true
) {
  lazy val cache: File =
    _cache.getOrElse {
      throw new RuntimeException(s"An analysis cache file is required.")
    }

  def withAbsolutePaths(relativeTo: File): AnalysisOptions = {
    this.copy(
      _cache = Util.normaliseOpt(Some(relativeTo))(_cache),
      cacheMap = Util.normaliseMap(Some(relativeTo))(cacheMap),
      rebaseMap = Util.normaliseMap(Some(relativeTo))(rebaseMap)
    )
  }
}
