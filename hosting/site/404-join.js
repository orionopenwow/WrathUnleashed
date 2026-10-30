// Add to www/404.html (GitHub Pages serves it for unknown paths) so invite links of the form
// https://openvanilla.app/join/<realm-id>#<secret> open the join page. The #secret never reaches any
// server: browsers keep the fragment, and this redirect carries it along client-side.
(function () {
  var m = location.pathname.match(/^\/join\/([a-z2-7]{16})\/?$/);
  if (m) location.replace("/join/?r=" + m[1] + location.hash);
})();
