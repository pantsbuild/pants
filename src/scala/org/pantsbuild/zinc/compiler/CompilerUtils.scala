/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.File
import java.net.URLClassLoader
import sbt.internal.inc.AnalyzingCompiler
import sbt.internal.inc.classpath.ClassLoaderCache
import sbt.io.Path
import xsbti.compile.{ClasspathOptionsUtil, CompilerCache => XCompilerCache, GlobalsCache, ZincCompilerUtil, ScalaInstance}
import org.pantsbuild.zinc.util.Util

object CompilerUtils {
  val JavaClassVersion = System.getProperty("java.class.version")

  private val residentCacheLimit = Util.intProperty("zinc.resident.cache.limit", 0)

  /**
   * Cache of classloaders: see https://github.com/pantsbuild/pants/issues/4744
   */
  private val classLoaderCache: Option[ClassLoaderCache] =
    Some(new ClassLoaderCache(new URLClassLoader(Array())))

  /**
   * Create a new scala compiler.
   */
  def newScalaCompiler(instance: ScalaInstance, bridgeJar: File): AnalyzingCompiler =
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
