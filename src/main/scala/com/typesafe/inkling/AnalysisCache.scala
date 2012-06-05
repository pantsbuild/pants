/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.inkling

import java.io.File
import java.lang.ref.SoftReference
import sbt.compiler.IC
import sbt.inc.Analysis
import scala.collection.mutable

object AnalysisCache {
  private val memoryCache = mutable.Map.empty[File, SoftReference[Analysis]]

  def get(cacheFile: File): Analysis = synchronized {
    val cached = if (memoryCache.isDefinedAt(cacheFile)) memoryCache(cacheFile).get else null
    if (cached ne null) cached else put(cacheFile, IC.readAnalysis(cacheFile))
  }

  def put(cacheFile: File, analysis: Analysis): Analysis = synchronized {
    memoryCache += cacheFile -> new SoftReference(analysis)
    analysis
  }
}
