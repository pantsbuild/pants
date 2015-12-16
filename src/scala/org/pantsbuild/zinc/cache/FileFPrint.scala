/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.cache

import java.io.{FileNotFoundException, File}
import com.google.common.hash.Hashing
import com.google.common.base.Charsets


class FileFPrint(val file: File, val fprint: String) {
  override def hashCode = fprint.hashCode

  override def equals(o: Any) = o match {
    case that: FileFPrint => fprint == that.fprint
    case _ => false
  }

  override def toString = "(%s: %s)".format(fprint, file.getPath)
}

object FileFPrint {
  private val HashFunction = Hashing.murmur3_128()
  private val LongStringLen = (2l^31).toString.size

  /**
   * NB: This used to SHA1 the entire analysis file to generate fingerprint, but in the context
   * of many, many small projects that is too expensive an operation. Instead, we use only the
   * analysis file name and lastModified time here.
   *
   * TODO: It should be relatively unlikely to encounter a collision here, but it would be good
   * to prevent it entirely by including a UUID in the header of the analysis file and using that
   * as its fingerprint.
   */
  def fprint(file: File): Option[FileFPrint] = {
    try {
      if (!file.exists()) {
        return None
      }
      val filePath = file.getCanonicalPath()
      val hasher = HashFunction.newHasher(filePath.size + (2 * LongStringLen))
      hasher.putString(filePath, Charsets.UTF_8)
      hasher.putLong(file.lastModified)
      Some(new FileFPrint(file, hasher.hash.toString))
    } catch {
      case e: FileNotFoundException => None
    }
  }
}
