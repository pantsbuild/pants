/**
 * Copyright (C) 2015 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc

import java.io.{File, IOException}
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import xsbti.Maybe
import xsbti.compile.{CompileAnalysis, DefinesClass, MiniSetup, PerClasspathEntryLookup}
import sbt.internal.inc.{Analysis, AnalysisStore, CompanionsStore, Locate, TextAnalysisFormat}
import sbt.io.{IO, Using}
import sbt.util.Logger
import sbt.util.Logger.o2m
import org.pantsbuild.zinc.cache.{Cache, FileFPrint}
import org.pantsbuild.zinc.cache.Cache.Implicits
import xsbti.api.Companions

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

  def getPCELookup = new PerClasspathEntryLookup {
    /**
     * Gets analysis for a classpath entry (if it exists) by translating its path to a potential
     * cache location and then checking the cache.
     */
    def analysis(classpathEntry: File): Maybe[CompileAnalysis] =
      o2m(analysisLocations.get(classpathEntry).flatMap(AnalysisMap.get))

    /**
     * An implementation of definesClass that will use analysis for an input directory to determine
     * whether it defines a particular class.
     *
     * TODO: This optimization is unnecessary for jars on the classpath, which are already indexed.
     * Can remove after the sbt jar output patch lands.
     */
    def definesClass(classpathEntry: File): DefinesClass = {
      getAnalysis(classpathEntry).map { analysis =>
        log.debug(s"Hit analysis cache for class definitions with ${classpathEntry}")
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
       analysisLocations.get(classpathEntry).flatMap(AnalysisMap.get)
  }
}

object AnalysisMap {
  /**
   * Static cache for compile analyses. Values must be Options because in get() we don't yet
   * know if, on a cache miss, the underlying file will yield a valid Analysis.
   */
  private val analysisCache =
    Cache[FileFPrint, Option[(CompileAnalysis, MiniSetup)]](Setup.Defaults.analysisCacheLimit)

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

  private def get(cacheFPrint: FileFPrint): Option[CompileAnalysis] =
    analysisCache.getOrElseUpdate(cacheFPrint) {
      // re-fingerprint the file on miss, to ensure that analysis hasn't changed since we started
      if (!FileFPrint.fprint(cacheFPrint.file).exists(_ == cacheFPrint)) {
        throw new IOException(s"Analysis at $cacheFPrint has changed since startup!")
      }
      AnalysisStore.cached(SafeFileBasedStore(cacheFPrint.file)).get()
    }.map(_._1)

  /**
   * Create an analysis store backed by analysisCache.
   */
  def cachedStore(cacheFile: File): AnalysisStore = {
    val fileStore = AnalysisStore.cached(SafeFileBasedStore(cacheFile))

    val fprintStore = new AnalysisStore {
      def set(analysis: CompileAnalysis, setup: MiniSetup) {
        fileStore.set(analysis, setup)
        FileFPrint.fprint(cacheFile) foreach { analysisCache.put(_, Some((analysis, setup))) }
      }
      def get(): Option[(CompileAnalysis, MiniSetup)] = {
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

/**
 * Safely update analysis file by writing to a temp file first
 * and only rename to the original file upon successful write.
 *
 * TODO: merge this upstream https://github.com/sbt/zinc/issues/178
 */
object SafeFileBasedStore {
  def apply(file: File): AnalysisStore = new AnalysisStore {
    override def set(analysis: CompileAnalysis, setup: MiniSetup): Unit = {
      val tmpAnalysisFile = File.createTempFile(file.getName, ".tmp")
      val analysisStore = PlainTextFileBasedStore(tmpAnalysisFile)
      analysisStore.set(analysis, setup)
      Files.move(tmpAnalysisFile.toPath, file.toPath, StandardCopyOption.REPLACE_EXISTING)
    }

    override def get(): Option[(CompileAnalysis, MiniSetup)] =
      PlainTextFileBasedStore(file).get
  }
}

/**
 * Zinc 1.0 changes its analysis file format to zip, and split into two files.
 * The following provides a plain text adaptor for pants parser. Long term though,
 * we should consider define an internal analysis format that's 1) more stable
 * 2) better performance because we can pick and choose only the fields we care about
 * - string processing in rebase can be slow for example.
 * https://github.com/pantsbuild/pants/issues/4039
 */
object PlainTextFileBasedStore {
  def apply(file: File): AnalysisStore = new AnalysisStore {
    override def set(analysis: CompileAnalysis, setup: MiniSetup): Unit = {
      Using.fileWriter(IO.utf8)(file) { writer => TextAnalysisFormat.write(writer, analysis, setup) }
    }

    override def get(): Option[(CompileAnalysis, MiniSetup)] =
      try { Some(getUncaught()) } catch { case _: Exception => None }
    def getUncaught(): (CompileAnalysis, MiniSetup) =
      Using.fileReader(IO.utf8)(file) { reader => TextAnalysisFormat.read(reader, noopCompanionsStore) }
  }

  val noopCompanionsStore = new CompanionsStore {
    override def get(): Option[(Map[String, Companions], Map[String, Companions])] = Some(getUncaught())
    override def getUncaught(): (Map[String, Companions], Map[String, Companions]) = (Map(), Map())
  }
}
