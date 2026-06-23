/* ── Carte Leaflet — Planification de déploiement KOSMOS ───────────────── */

var map = L.map('map', { zoomControl: true }).setView([47.5, -3.5], 9);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19
}).addTo(map);

/* ── Tooltip coordonnées ────────────────────────────────────────────────── */
var tip = document.getElementById('coord-tip');

map.on('mousemove', function (e) {
  tip.style.display = 'block';
  tip.style.left = (e.originalEvent.clientX + 14) + 'px';
  tip.style.top  = (e.originalEvent.clientY - 30) + 'px';
  tip.textContent = e.latlng.lat.toFixed(6) + ',  ' + e.latlng.lng.toFixed(6);
});

map.on('mouseout', function () { tip.style.display = 'none'; });

/* ── Marqueurs numérotés ────────────────────────────────────────────────── */
var markers = [];

function _icon(n, label) {
  var text = label || String(n);
  return L.divIcon({
    className: '',
    html: '<div style="background:#2778a2;color:#fff;border:2px solid #7ec8e3;'
        + 'border-radius:50%;min-width:26px;height:26px;line-height:22px;'
        + 'text-align:center;font:bold 11px sans-serif;padding:0 4px;'
        + 'box-shadow:0 2px 6px #0008;white-space:nowrap;">'
        + n + '</div>',
    iconSize: null, iconAnchor: [13, 13], popupAnchor: [0, -16]
  });
}

function _updateMarkerPopup(m, label) {
  m.setPopupContent(
    '<b>' + label + '</b><br>'
    + m.getLatLng().lat.toFixed(6) + ', ' + m.getLatLng().lng.toFixed(6)
  );
}

/* ── Pont Qt WebChannel ─────────────────────────────────────────────────── */
var bridge = null;

new QWebChannel(qt.webChannelTransport, function (ch) {
  bridge = ch.objects.planBridge;
});

/* ── API publique (appelée depuis Python via runJavaScript) ─────────────── */

function updateMarkerLabel(idx, label) {
  if (idx < 0 || idx >= markers.length) return;
  var m = markers[idx];
  m.setIcon(_icon(idx + 1, label));
  _updateMarkerPopup(m, label);
}

function removeMarkerByIndex(idx) {
  if (idx < 0 || idx >= markers.length) return;
  map.removeLayer(markers[idx]);
  markers.splice(idx, 1);
  markers.forEach(function (m, i) {
    m.setIcon(_icon(i + 1));
    _updateMarkerPopup(m, 'Point ' + (i + 1));
  });
}

function clearAllMarkers() {
  markers.forEach(function (m) { map.removeLayer(m); });
  markers = [];
}

/* ── Clic sur la carte → ajout d'un waypoint ───────────────────────────── */
map.on('click', function (e) {
  var lat = e.latlng.lat, lng = e.latlng.lng;
  var idx = markers.length;
  var defaultLabel = 'Point ' + (idx + 1);

  var m = L.marker([lat, lng], { icon: _icon(idx + 1) })
           .addTo(map)
           .bindPopup('<b>' + defaultLabel + '</b><br>'
             + lat.toFixed(6) + ', ' + lng.toFixed(6));
  markers.push(m);

  if (bridge) {
    bridge.onPointAdded(JSON.stringify({
      index: idx,
      lat:   lat.toFixed(6),
      lng:   lng.toFixed(6),
      label: defaultLabel
    }));
  }
});
