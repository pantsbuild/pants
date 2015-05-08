/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import com.martiansoftware.nailgun.NGConstants
import java.io.{ ByteArrayOutputStream, DataInputStream, File, OutputStream }
import java.net.{ InetAddress, Socket }
import java.nio.ByteBuffer
import java.util.{ List => JList }
import scala.annotation.tailrec
import scala.collection.JavaConverters._

object ZincClient {
  object Chunk {
    val Argument  = NGConstants.CHUNKTYPE_ARGUMENT
    val Command   = NGConstants.CHUNKTYPE_COMMAND
    val Directory = NGConstants.CHUNKTYPE_WORKINGDIRECTORY
    val StdOut    = NGConstants.CHUNKTYPE_STDOUT
    val StdErr    = NGConstants.CHUNKTYPE_STDERR
    val Exit      = NGConstants.CHUNKTYPE_EXIT
  }

  object Exception {
    val ServerExit    = NGConstants.EXIT_EXCEPTION
    val NoSuchCommand = NGConstants.EXIT_NOSUCHCOMMAND
    val ClientReceive = 897
  }
}

/**
 * Client for talking directly to a nailgun server from another JVM.
 */
class ZincClient(val address: InetAddress, val port: Int) {
  def this(address: String, port: Int) = this(InetAddress.getByName(address), port)
  def this(port: Int) = this(InetAddress.getByName(null), port)
  def this() = this(Nailgun.DefaultPort)

  /**
   * Send a zinc command to a currently running nailgun server.
   * All output goes to specified output streams. Exit code is returned.
   * @throws java.net.ConnectException if the zinc server is not available
   */
  @throws(classOf[java.net.ConnectException])
  def run(args: Seq[String], cwd: File, out: OutputStream, err: OutputStream): Int =
    send("zinc", args, cwd, out, err)

  /**
   * Java API for sending a zinc command to a currently running nailgun server.
   * All output goes to specified output streams. Exit code is returned.
   * @throws java.net.ConnectException if the zinc server is not available
   */
  @throws(classOf[java.net.ConnectException])
  def run(args: JList[String], cwd: File, out: OutputStream, err: OutputStream): Int =
    send("zinc", args.asScala, cwd, out, err)

  /**
   * Run a single argument-less nailgun command to a single output stream.
   * Exit code is returned.
   * @throws java.net.ConnectException if the zinc server is not available
   */
  @throws(classOf[java.net.ConnectException])
  def run(command: String, out: OutputStream): Int = {
    send(command, Seq.empty, Setup.Defaults.userDir, out, out)
  }

  /**
   * Run a single argument-less nailgun command, with dummy output streams
   * and default working directory. Exit code is returned.
   * @throws java.net.ConnectException if the zinc server is not available
   */
  @throws(classOf[java.net.ConnectException])
  def run(command: String): Int = {
    val dummyOut = new ByteArrayOutputStream
    send(command, Seq.empty, Setup.Defaults.userDir, dummyOut, dummyOut)
  }

  /**
   * Send a command to a currently running nailgun server.
   * Possible commands are "zinc", "status", and "shutdown".
   * All output goes to specified output streams. Exit code is returned.
   * @throws java.net.ConnectException if the zinc server is not available
   */
  def send(command: String, args: Seq[String], cwd: File, out: OutputStream, err: OutputStream): Int = {
    val socket  = new Socket(address, port)
    val sockout = socket.getOutputStream
    val sockin  = new DataInputStream(socket.getInputStream)
    sendCommand(command, args, cwd, sockout)
    val exitCode = receiveOutput(sockin, out, err)
    sockout.close(); sockin.close(); socket.close()
    exitCode
  }

  /**
   * Check if a nailgun server is currently available.
   */
  def serverAvailable(): Boolean = {
    try {
      val exitCode = run("ng-version")
      exitCode == 0
    } catch {
      case _: java.io.IOException => false
    }
  }

  /**
   * Start a zinc server in a separate process, if not already available.
   */
  def requireServer(options: Seq[String], classpath: Seq[File], timeout: String): Boolean = {
    if (!serverAvailable) {
      Nailgun.fork(options, classpath, port, timeout)
      // give some time for startup
      var count = 0
      while (!serverAvailable && (count < 50)) {
        try { Thread.sleep(100) } catch { case _: InterruptedException => }
        count += 1
      }
    }
    serverAvailable
  }

  /**
   * Java API to start a zinc server in a separate process, if not already available.
   */
  def requireServer(options: JList[String], classpath: JList[File], timeout: String): Boolean =
    requireServer(options.asScala, classpath.asScala, timeout)

  /**
   * Output server status by sending the "status" command.
   */
  def serverStatus(out: OutputStream): Boolean = {
    try {
      val exitCode = run("status", out)
      exitCode == 0
    } catch {
      case _: java.io.IOException => false
    }
  }

  /**
   * Return server status as a string.
   */
  def serverStatus(): String = {
    val bytes = new ByteArrayOutputStream
    val success = serverStatus(bytes)
    bytes.toString
  }

  /**
   * Shutdown any running zinc server by sending the "shutdown" command.
   */
  def shutdownServer(): Boolean = {
    try {
      val exitCode = run("shutdown")
      exitCode == 0 || exitCode == ZincClient.Exception.ClientReceive
    } catch {
      case _: java.io.IOException => false
    }
  }

  private def sendCommand(command: String, args: Seq[String], cwd: File, out: OutputStream): Unit = {
    import ZincClient.Chunk.{ Argument, Command, Directory }
    args foreach { arg => putChunk(Argument, arg, out) }
    putChunk(Directory, cwd.getCanonicalPath, out)
    putChunk(Command, command, out)
  }

  @tailrec
  private def receiveOutput(in: DataInputStream, out: OutputStream, err: OutputStream): Int = {
    import ZincClient.Chunk.{ Exit, StdOut, StdErr }
    val exitCode =
      try {
        val (chunkType, data) = getChunk(in)
        chunkType match {
          case Exit   => Some(new String(data).toInt)
          case StdOut => out.write(data); None
          case StdErr => err.write(data); None
        }
      } catch {
        case _: Exception => Some(ZincClient.Exception.ClientReceive)
      }
    if (exitCode.isDefined) exitCode.get else receiveOutput(in, out, err)
  }

  private def createHeader(size: Int, chunkType: Byte): Array[Byte] = {
    ByteBuffer.allocate(5).putInt(size).put(chunkType).array
  }

  private def readHeader(array: Array[Byte]): (Int, Byte) = {
    val buffer = ByteBuffer.wrap(array, 0, 5)
    (buffer.getInt, buffer.get)
  }

  private def putChunk(chunkType: Byte, data: String, output: OutputStream): Unit = {
    output.write(createHeader(data.length, chunkType))
    output.write(data.getBytes)
  }

  private def getChunk(input: DataInputStream): (Byte, Array[Byte]) = {
    val header = Array.ofDim[Byte](5)
    input.readFully(header)
    val (size, chunkType) = readHeader(header)
    val data = Array.ofDim[Byte](size)
    input.readFully(data)
    (chunkType, data)
  }
}
