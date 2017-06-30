/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.analysis

import java.io.File
import java.nio.file.Path

import sbt.internal.inc.{AnalysisMappersAdapter, Mapper}


/**
 * Given a Set of Path bases and destination bases, adapts written analysis to rewrite
 * all of the bases.
 *
 * Intended usecase is to rebase each distinct non-portable base path contained in the analysis:
 * in pants this is generally
 *   1) the buildroot
 *   2) the workdir (generally named `.pants.d`, but not always located under the buildroot)
 *   3) the base of the JVM that is in use
 */
class PortableAnalysisMappers(rebaseMap: Map[File, File]) extends AnalysisMappersAdapter {
  private val rebaser = {
    val rebases =
      rebaseMap
        .toSeq
        .map {
          case (k, v) => (k.toPath, v.toPath)
        }
        .toSet
    val forWrite = PortableAnalysisMappers.mkFileRebaser(rebases)
    val forRead = PortableAnalysisMappers.mkFileRebaser(rebases.map { case (src, dst) => (dst, src) })
    Mapper.forFile.map(forRead, forWrite)
  }

  // TODO: scalac/javac options and a few other items are not currently rebased.
  override val outputDirMapper: Mapper[File] = rebaser
  override val sourceDirMapper: Mapper[File] = rebaser
  override val sourceMapper: Mapper[File] = rebaser
  override val productMapper: Mapper[File] = rebaser
  override val binaryMapper: Mapper[File] = rebaser
  override val classpathMapper: Mapper[File] = rebaser
}

object PortableAnalysisMappers {
  private def mkFileRebaser(rebases: Set[(Path, Path)]): File => File = {
    // Sort the rebases from longest to shortest (to ensure that a prefix is rebased
    // before a suffix).
    val orderedRebases =
      rebases.toSeq.sortBy {
        case (path, slug) => -path.toString.size
      }
    val rebaser: File => File = { f =>
      val p = f.toPath
      // Attempt each rebase in length order, applying the longest one that matches.
      orderedRebases
        .collectFirst {
          case (from, to) if p.startsWith(from) =>
            to.resolve(from.relativize(p)).toFile
        }
        .getOrElse(f)
    }
    rebaser
  }
}
