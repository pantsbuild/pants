/**
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc

import java.io.{
  File,
  IOException
}

import sbt.{
  CompileSetup,
  Logger
}
import sbt.inc.{
  Analysis,
  AnalysisStore,
  FileBasedStore,
  Locate
}

import org.pantsbuild.zinc.cache.{
  Cache,
  FileFPrint
}
import org.pantsbuild.zinc.cache.Cache.Implicits

/**
 * A facade around the analysis cache to:
 *   1) map between classpath entries and cache locations
 *   2) use analysis for `definesClass` when it is available
 *
 * SBT uses the `definesClass` and `getAnalysis` methods in order to load the APIs for upstream
 * classes. For a classpath containing multiple entries, sbt will call `definesClass` sequentially
 * on classpath entries until it finds a classpath entry defining a particular class. When it finds
 * the appropriate classpath entry, it will use `getAnalysis` to fetch the API for that class.
 */
case class AnalysisMap private[AnalysisMap] (
  // a map of classpath entries to cache file fingerprints, excluding the current compile destination
  analysisLocations: Map[File, FileFPrint],
  // log
  log: Logger
) {
  /**
   * An implementation of definesClass that will use analysis for an input directory to determine
   * whether it defines a particular class.
   *
   * TODO: This optimization is unnecessary for jars on the classpath, which are already indexed.
   * Can remove after the sbt jar output patch lands.
   */
  def definesClass(classpathEntry: File): String => Boolean =
    getAnalysis(classpathEntry).map { analysis =>
      log.debug(s"Hit analysis cache for class definitions with ${classpathEntry}")
      // strongly hold the classNames, and transform them to ensure that they are unlinked from
      // the remainder of the analysis
      analysis.relations.classes.reverseMap.keys.toList.toSet
    }.map { classes =>
      (s: String) => classes(s)
    }.getOrElse {
      // no analysis: return a function that will scan instead
      Locate.definesClass(classpathEntry)
    }

  /**
   * Gets analysis for a classpath entry (if it exists) by translating its path to a potential
   * cache location and then checking the cache.
   */
  def getAnalysis(classpathEntry: File): Option[Analysis] =
    analysisLocations.get(classpathEntry).flatMap(AnalysisMap.get)
}

object AnalysisMap {
  /**
   * Static cache for compile analyses. Values must be Options because in get() we don't yet
   * know if, on a cache miss, the underlying file will yield a valid Analysis.
   */
  private val analysisCache =
    Cache[FileFPrint, Option[(Analysis, CompileSetup)]](Setup.Defaults.analysisCacheLimit)

  def create(
    // a map of classpath entries to cache file locations, excluding the current compile destination
    analysisLocations: Map[File, File],
    // log
    log: Logger
  ): AnalysisMap =
    AnalysisMap(
      // create fingerprints for all inputs at startup
      analysisLocations.flatMap {
        case (classpathEntry, cacheFile) => FileFPrint.fprint(cacheFile).map(classpathEntry -> _)
      },
      log
    )

  private def get(cacheFPrint: FileFPrint): Option[Analysis] =
    analysisCache.getOrElseUpdate(cacheFPrint) {
      // re-fingerprint the file on miss, to ensure that analysis hasn't changed since we started
      if (!FileFPrint.fprint(cacheFPrint.file).exists(_ == cacheFPrint)) {
        throw new IOException(s"Analysis at $cacheFPrint has changed since startup!")
      }
      FileBasedStore(cacheFPrint.file).get
    }.map(_._1)

  /**
   * Create an analysis store backed by analysisCache.
   */
  def cachedStore(cacheFile: File): AnalysisStore = {
    val fileStore = AnalysisStore.cached(FileBasedStore(cacheFile))

    val fprintStore = new AnalysisStore {
      def set(analysis: Analysis, setup: CompileSetup) {
        fileStore.set(analysis, setup)
        FileFPrint.fprint(cacheFile) foreach { analysisCache.put(_, Some((analysis, setup))) }
      }
      def get(): Option[(Analysis, CompileSetup)] = {
        FileFPrint.fprint(cacheFile) flatMap { fprint =>
          analysisCache.getOrElseUpdate(fprint) {
            fileStore.get
          }
        }
      }
    }

    AnalysisStore.sync(AnalysisStore.cached(fprintStore))
  }
}
