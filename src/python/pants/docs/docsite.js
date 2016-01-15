// Ping Google analytics
(function(i,s,o,g,r,a,m){i['GoogleAnalyticsObject']=r;i[r]=i[r]||function(){
    (i[r].q=i[r].q||[]).push(arguments)},i[r].l=1*new Date();a=s.createElement(o),
    m=s.getElementsByTagName(o)[0];a.async=1;a.src=g;m.parentNode.insertBefore(a,m)
    })(window,document,'script','//www.google-analytics.com/analytics.js','ga');

ga('create', 'UA-39101739-2', 'auto');
ga('send', 'pageview');

var ToggleNavs = function() {
  if (document && document.querySelectorAll) {
    var navs = document.querySelectorAll('.bignav');
    if (!navs) { return; }
    var old_visibility = '';
    if (navs[0] && navs[0].style && navs[0].style.display) {
      old_visibility = navs[0].style.display;
    }

    var new_visibility = 'block';
    if (old_visibility == 'block') {
      new_visibility = '';
    }
    for (ix = 0; ix < navs.length; ix++) {
      navs[ix].style.display = new_visibility;
    }
  }
};

window.onload = function(e) {
  var navtoggler = document.getElementById('navtoggler');
  navtoggler.onclick = ToggleNavs;
};

