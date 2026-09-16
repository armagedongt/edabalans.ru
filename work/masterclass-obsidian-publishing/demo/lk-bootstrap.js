// Local context only: canonical course UI stays in its non-server preview mode.
window.EdabalansAppHost = location.origin;
window.EdabalansAppContext = {accountUrl: '/day-1'};
if (location.pathname === '/material' || location.pathname === '/lk') {
  const route = new URL(location.href);
  if (!route.searchParams.has('course_material')) {
    route.searchParams.set('course_day', '1');
    route.searchParams.set('course_material', 'local-day-01-md-formatting');
    history.replaceState(null, '', route);
  }
}
