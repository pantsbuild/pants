/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.File
import java.net.URLClassLoader
import sbt.internal.inc.{
  AnalyzingCompiler,
  CompileOutput,
  IncrementalCompilerImpl,
  RawCompiler,
  ScalaInstance,
  javac,
  ZincUtil
}
import sbt.internal.inc.classpath.ClassLoaderCache
import sbt.io.Path
import sbt.io.syntax._
import sbt.util.Logger
import xsbti.compile.{
  ClasspathOptionsUtil,
  CompilerCache,
  Compilers,
  GlobalsCache,
  Inputs,
  JavaTools,
  ScalaCompiler,
  ScalaInstance => XScalaInstance,
  ZincCompilerUtil
}

import scala.compat.java8.OptionConverters._

import org.pantsbuild.zinc.cache.Cache
import org.pantsbuild.zinc.cache.Cache.Implicits
import org.pantsbuild.zinc.util.Util

object CompilerUtils {
  val CompilerInterfaceId = "compiler-interface"
  val JavaClassVersion = System.getProperty("java.class.version")

  private val compilerCacheLimit = Util.intProperty("zinc.compiler.cache.limit", 5)
  private val residentCacheLimit = Util.intProperty("zinc.resident.cache.limit", 0)

  /**
   * Static cache for zinc compilers.
   */
  private val compilerCache = Cache[CompilerCacheKey, Compilers](compilerCacheLimit)

  /**
   * Static cache for resident scala compilers.
   */
  private val residentCache: GlobalsCache = {
    val maxCompilers = residentCacheLimit
    if (maxCompilers <= 0)
      CompilerCache.fresh
    else
      CompilerCache.createCacheFor(maxCompilers)
  }

  /**
   * Cache of classloaders: see https://github.com/pantsbuild/pants/issues/4744
   */
  private val classLoaderCache: Option[ClassLoaderCache] =
    Some(new ClassLoaderCache(new URLClassLoader(Array())))

  /**
   * Get or create a zinc compiler based on compiler setup.
   */
  def getOrCreate(settings: Settings, log: Logger): Compilers = {
    val setup = CompilerCacheKey(settings)
    compilerCache.getOrElseUpdate(setup) {
      val instance     = scalaInstance(setup)
      val interfaceJar = compilerInterface(setup, instance, log)
      val scalac       = newScalaCompiler(instance, interfaceJar)
      ZincUtil.compilers(instance, ClasspathOptionsUtil.auto, setup.javaHome, scalac)
    }
  }

  /**
   * Get the instance of the GlobalsCache.
   */
  def getGlobalsCache = residentCache

  /**
   * Create a new scala compiler.
   */
  def newScalaCompiler(instance: XScalaInstance, interfaceJar: File): AnalyzingCompiler =
    new AnalyzingCompiler(
      instance,
      ZincCompilerUtil.constantBridgeProvider(instance, interfaceJar),
      ClasspathOptionsUtil.auto,
      _ => (),
      classLoaderCache
    )

  /**
   * Create the scala instance for the compiler. Includes creating the classloader.
   */
  def scalaInstance(setup: CompilerCacheKey): XScalaInstance = {
    import setup.{scalaCompiler, scalaExtra, scalaLibrary}
    val allJars = scalaLibrary +: scalaCompiler +: scalaExtra
    val loader = scalaLoader(allJars)
    val version = scalaVersion(loader)
    new ScalaInstance(version.getOrElse("unknown"), loader, scalaLibrary, scalaCompiler, allJars.toArray, version)
  }

  /**
   * Create a new classloader with the root loader as parent (to avoid zinc itself being included).
   */
  def scalaLoader(jars: Seq[File]) =
    new URLClassLoader(
      Path.toURLs(jars),
      sbt.internal.inc.classpath.ClasspathUtilities.rootLoader
    )

  /**
   * Get the actual scala version from the compiler.properties in a classloader.
   * The classloader should only contain one version of scala.
   */
  def scalaVersion(scalaLoader: ClassLoader): Option[String] = {
    Util.propertyFromResource("compiler.properties", "version.number", scalaLoader)
  }

  /**
   * Get the compiler interface for this compiler setup. Compile it if not already cached.
   * NB: This usually occurs within the compilerCache entry lock, but in the presence of
   * multiple zinc processes (ie, without nailgun) we need to be more careful not to clobber
   * another compilation attempt.
   */
  def compilerInterface(setup: CompilerCacheKey, scalaInstance: XScalaInstance, log: Logger): File = {
    def compile(targetJar: File): Unit =
      AnalyzingCompiler.compileSources(
        Seq(setup.compilerBridgeSrc),
        targetJar,
        Seq(setup.compilerInterface),
        CompilerInterfaceId,
        new RawCompiler(scalaInstance, ClasspathOptionsUtil.auto, log),
        log
      )
    val dir = setup.cacheDir / interfaceId(scalaInstance.actualVersion)
    val interfaceJar = dir / (CompilerInterfaceId + ".jar")
    if (!interfaceJar.isFile) {
      dir.mkdirs()
      val tempJar = File.createTempFile("interface-", ".jar.tmp", dir)
      try {
        compile(tempJar)
        tempJar.renameTo(interfaceJar)
      } finally {
        tempJar.delete()
      }
    }
    interfaceJar
  }

  def interfaceId(scalaVersion: String) = CompilerInterfaceId + "-" + scalaVersion + "-" + JavaClassVersion
}
