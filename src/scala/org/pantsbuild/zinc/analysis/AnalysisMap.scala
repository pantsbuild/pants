/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.analysis

import java.io.{File, IOException}
import java.util.Optional

import scala.compat.java8.OptionConverters._

import sbt.internal.inc.{Analysis, AnalysisStore, CompanionsStore, FileBasedStore, Locate}
import sbt.util.Logger
import xsbti.api.Companions
import xsbti.compile.{CompileAnalysis, DefinesClass, MiniSetup, PerClasspathEntryLookup}

import org.pantsbuild.zinc.cache.Cache.Implicits
import org.pantsbuild.zinc.cache.{Cache, FileFPrint}
import org.pantsbuild.zinc.util.Util

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
class AnalysisMap private[AnalysisMap] (
  // a map of classpath entries to cache file fingerprints, excluding the current compile destination
  analysisLocations: Map[File, FileFPrint],
  // a Map of File bases to destinations to re-relativize them to
  rebases: Map[File, File]
) {
  private val analysisMappers = new PortableAnalysisMappers(rebases)

  def getPCELookup = new PerClasspathEntryLookup {
    /**
     * Gets analysis for a classpath entry (if it exists) by translating its path to a potential
     * cache location and then checking the cache.
     */
    def analysis(classpathEntry: File): Optional[CompileAnalysis] =
      analysisLocations.get(classpathEntry).flatMap(cacheLookup).asJava

    /**
     * An implementation of definesClass that will use analysis for an input directory to determine
     * whether it defines a particular class.
     *
     * TODO: This optimization is unnecessary for jars on the classpath, which are already indexed.
     * Can remove after the sbt jar output patch lands.
     */
    def definesClass(classpathEntry: File): DefinesClass = {
      getAnalysis(classpathEntry).map { analysis =>
        // strongly hold the classNames, and transform them to ensure that they are unlinked from
        // the remainder of the analysis
        val classNames = analysis.asInstanceOf[Analysis].relations.srcProd.reverseMap.keys.toList.toSet.map(
          (f: File) => filePathToClassName(f))
        new ClassNamesDefinesClass(classNames)
      }.getOrElse {
        // no analysis: return a function that will scan instead
        Locate.definesClass(classpathEntry)
      }
    }

    private class ClassNamesDefinesClass(classes: Set[String]) extends DefinesClass {
      override def apply(className: String): Boolean = classes(className)
    }

    private def filePathToClassName(file: File): String = {
      // Extract className from path, for example:
      //   .../.pants.d/compile/zinc/.../current/classes/org/pantsbuild/example/hello/exe/Exe.class
      //   => org.pantsbuild.example.hello.exe.Exe
      file.getAbsolutePath.split("current/classes")(1).drop(1).replace(".class", "").replaceAll("/", ".")
    }

    /**
     * Gets analysis for a classpath entry (if it exists) by translating its path to a potential
     * cache location and then checking the cache.
     */
    def getAnalysis(classpathEntry: File): Option[CompileAnalysis] =
       analysisLocations.get(classpathEntry).flatMap(cacheLookup)
  }

  def cachedStore(cacheFile: File): AnalysisStore =
    AnalysisStore.sync(
      new AnalysisStore {
        val fileStore = mkFileBasedStore(cacheFile)

        def set(analysis: CompileAnalysis, setup: MiniSetup) {
          fileStore.set(analysis, setup)
          FileFPrint.fprint(cacheFile).foreach { fprint =>
            AnalysisMap.analysisCache.put(fprint, Some((analysis, setup)))
          }
        }

        def get(): Option[(CompileAnalysis, MiniSetup)] = {
          FileFPrint.fprint(cacheFile) flatMap { fprint =>
            AnalysisMap.analysisCache.getOrElseUpdate(fprint) {
              fileStore.get
            }
          }
        }
      }
    )

  private def cacheLookup(cacheFPrint: FileFPrint): Option[CompileAnalysis] =
    AnalysisMap.analysisCache.getOrElseUpdate(cacheFPrint) {
      // re-fingerprint the file on miss, to ensure that analysis hasn't changed since we started
      if (!FileFPrint.fprint(cacheFPrint.file).exists(_ == cacheFPrint)) {
        throw new IOException(s"Analysis at $cacheFPrint has changed since startup!")
      }
      mkFileBasedStore(cacheFPrint.file).get()
    }.map(_._1)

  private def mkFileBasedStore(file: File): AnalysisStore = FileBasedStore(file, analysisMappers)
}

object AnalysisMap {
  private val analysisCacheLimit = Util.intProperty("zinc.analysis.cache.limit", 100)
  /**
   * Static cache for compile analyses. Values must be Options because in get() we don't yet
   * know if, on a cache miss, the underlying file will yield a valid Analysis.
   */
  private val analysisCache =
    Cache[FileFPrint, Option[(CompileAnalysis, MiniSetup)]](analysisCacheLimit)

  def create(analysisLocations: Map[File, File], rebases: Map[File, File]): AnalysisMap =
    new AnalysisMap(
      // create fingerprints for all inputs at startup
      analysisLocations.flatMap {
        case (classpathEntry, cacheFile) => FileFPrint.fprint(cacheFile).map(classpathEntry -> _)
      },
      rebases
    )
}
