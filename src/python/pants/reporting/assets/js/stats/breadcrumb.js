// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Namespacing.
pants = pants || {};
pants.stats = pants.stats || {};
pants.stats.breadcrumb = pants.stats.breadcrumb || {};


// A widget showing the date of the data currently shown in the table, and
// a breadcrumb to the workunit we're currently drilled down to.
pants.stats.breadcrumb.init = function(selector) {
  var container = $(selector);

  var dateContainer = $('<span class="stats-date"></span>').appendTo(container);
  var crumbContainer = $('<span class="stats-crumb"></span>').appendTo(container);

  function showBreadcrumbs(workunit) {
    crumbContainer.empty();
    var crumbs = workunit.split(':');
    var path = [];
    _.each(crumbs, function(crumb) {
      path.push(crumb);
      var parentWorkunit = path.join(':');
      if (path.length > 1) {
        $('<span>:</span>').appendTo(crumbContainer);
      }
      $('<a href="#">' + crumb + '</a>').
          appendTo(crumbContainer).
          click(function(evt) {
            evt.preventDefault();
            $(document).triggerHandler('pants:stats:show', {
              workunit: parentWorkunit
            });
            return false;
          });
    });
  }

  // Set up event handling.

  $(document).on('pants:date:select', function(e, data) {
    dateContainer.html('[' + data.date + ']');
  });

  $(document).on('pants:stats:show', function(e, data) {
    showBreadcrumbs(data.workunit);
  });
};
