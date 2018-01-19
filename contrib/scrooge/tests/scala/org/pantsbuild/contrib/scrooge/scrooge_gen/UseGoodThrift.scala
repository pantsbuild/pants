package org.pantsbuild.contrib.scrooge.scrooge_gen

// NOTE: FutureIface is deprecated in a later version of scrooge according to
//       https://twitter.github.io/scrooge/Finagle.html#creating-a-server
class UseGoodThrift extends all.your.base.thriftscala.MyService.FutureIface {
  def getNumber(x: Int): com.twitter.util.Future[Int] = {
    com.twitter.util.Future[Int](1)
  }
}
