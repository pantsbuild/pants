// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// A stats visualization page.
// The page consists of the following widgets:
//   - Line charts of time spent in various selected workunits, by date.
//   - A table of the time breakdown per workunit on a specific date. Each workunit has
//     a checkbox allowing the user to show/hide line charts for that workunit, and each
//     workunit name is clickable, allowing the user to drill down onto just that workunit.
//   - Breadcrumb navigation, so the user can ascend back up the workunit hierarchy.

// TODO: We don't use any fancy js module frameworks. We hand-roll trivial namespacing and
// data-hiding in the Crockford style, and assume that all deps are available (by manually adding
// them in the HTML). Should be fine for now, but future JS mavens may wish to modernize this.

google.load('visualization', '1.0', {'packages':['line', 'table']});

// Namespacing.
pants = pants || {};
pants.stats = pants.stats || {};


pants.stats.initPage = function() {
  var statsData;

  // Proceed only after all 3 async loads below have completed.
  var initAfterLoad = _.after(3, doInit);

  // 1. Ensure DOM is loaded.
  $(initAfterLoad);

  // 2. Ensure google visualization package is loaded.
  google.setOnLoadCallback(initAfterLoad);

  // 3. Ensure stats data is loaded.
  $.ajax('/statsdata/', {
    success: function(data, textStatus, jqXHR) {
      statsData = data;
      initAfterLoad();
    },
    error: function(jqXHR, textStatus, errorThrown) {
      showError('Failed to load stats data: ' + jqXHR.responseText +
                '.<br>Status: ' + jqXHR.status + ' (' + jqXHR.statusText + ').');
    }
  });

  function showError(msg) {
    $('.error-msg').toggleClass('error-msg-hidden error-msg-shown').html(msg);
  }

  function doInit() {
    // Create all the widgets.
    if (statsData) {
      var matrix = pants.matrix.createDateWorkunitMatrix(statsData);
      pants.stats.chart.init('.timing-line-chart', matrix);
      pants.stats.table.init('.timing-drilldown-table', matrix);
      pants.stats.breadcrumb.init('.timing-drilldown-breadcrumbs');

      // Initially show the main workunit, on the latest date.
      var dates = [];
      matrix.eachRow(function(rowLabel) { dates.push(rowLabel); });
      var latestDate = _.last(dates);
      $(document).triggerHandler('pants:date:select', { date: latestDate });
      $(document).triggerHandler('pants:stats:show', { workunit: 'main' });
    }
  }
};
