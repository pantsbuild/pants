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
  val JavaClassVersion = System.getProperty("java.class.version")

  private val compilerCacheLimit = Util.intProperty("zinc.compiler.cache.limit", 5)
  private val residentCacheLimit = Util.intProperty("zinc.resident.cache.limit", 0)

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
   * Get the instance of the GlobalsCache.
   */
  def getGlobalsCache = residentCache

  /**
   * Create a new scala compiler.
   */
  def newScalaCompiler(instance: XScalaInstance, bridgeJar: File): AnalyzingCompiler =
    new AnalyzingCompiler(
      instance,
      ZincCompilerUtil.constantBridgeProvider(instance, bridgeJar),
      ClasspathOptionsUtil.auto,
      _ => (),
      classLoaderCache
    )

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

}
