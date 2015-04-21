/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.{FileNotFoundException, FileInputStream, InputStream, File}
import java.security.MessageDigest


class FileFPrint(val file: File, val fprint: String) {
  override def hashCode = fprint.hashCode

  override def equals(o: Any) = o match {
    case that: FileFPrint => fprint == that.fprint
    case _ => false
  }

  override def toString = "(%s: %s)".format(fprint, file.getPath)
}

object FileFPrint {
  def fprint(file: File): Option[FileFPrint] = {
    var is: Option[InputStream] = None
    val md = MessageDigest.getInstance("SHA1")
    val buf = new Array[Byte](8192)
    var n = 0
    try {
      is = Some(new FileInputStream(file))
      while ({n = (is map {_.read(buf)}).getOrElse(-1); n != -1}) { md.update(buf, 0, n) }
      val ret = Some(md.digest().map("%02X" format _).mkString)
      ret map { new FileFPrint(file, _) }
    } catch {
      case e: FileNotFoundException => None
    } finally {
      is foreach { _.close }
    }
  }
}
