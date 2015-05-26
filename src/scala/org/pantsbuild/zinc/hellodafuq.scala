package org.pantsbuild.zinc

import sbt.Level

object HelloDafuq {
    val logger = Util.logger(false, Level.Info, false)
    def main(args: Array[String]) {
      logger.info("Test!")
      logger.logRaw("HELLO MOTHERFUCKAAAAAAAAAZ")
    }
}
