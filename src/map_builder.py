from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

import folium
from folium.plugins import Fullscreen, HeatMap, MarkerCluster, MeasureControl, MiniMap

from config import BASEMAPS, AppConfig
from geo_utils import bounds_from_points


def _add_basemaps(fmap: folium.Map, default_name: str = "CartoDB Positron"):
    """Add basemaps defined in config.BASEMAPS. One named `default_name` is visible initially."""
    for name, meta in BASEMAPS.items():
        kwargs = {
            "tiles": meta["url"],
            "attr": meta.get("attr", ""),
            "name": name,
            "control": True,
            "overlay": False,
            "show": (name == default_name),
        }
        if "subdomains" in meta:
            kwargs["subdomains"] = meta["subdomains"]
        if "max_zoom" in meta:
            kwargs["max_zoom"] = meta["max_zoom"]
        folium.TileLayer(**kwargs).add_to(fmap)


# ---------------- CSS: layout, sidebar, gallery, popup/overlay ----------------
def _css_for(map_id: str) -> str:
    return f"""
<style>
html, body {{
  margin: 0; padding: 0;
  width: 100%; height: 100%;
  font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
}}
/* Map fills viewport minus right sidebar */
#{map_id} {{
  position: fixed;
  top: 0; left: 0; bottom: 0; right: 420px;
}}
/* Right sidebar (fixed column) */
#gallery-panel {{
  position: fixed;
  top: 0; right: 0; bottom: 0;
  width: 420px; max-width: 40%;
  overflow-y: auto;
  background: #fff;
  border-left: 1px solid #ddd;
  padding: 12px;
  box-shadow: -2px 0 8px rgba(0,0,0,0.08);
  z-index: 9999;
}}
#gallery-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }}
#gallery-header h3 {{ margin:0; font-size:16px; }}
#gallery-controls {{ display:flex; gap:10px; align-items:center; font-size:12px; }}
#gallery-controls label {{ display:flex; gap:6px; align-items:center; cursor:pointer; user-select:none; }}
#gallery-refresh {{ padding:4px 8px; border-radius:8px; border:1px solid rgba(0,0,0,0.1); background:#fff; cursor:pointer; }}
#gallery-count {{ font-size:12px; color:#666; margin:6px 0 8px; }}
.badge {{ background:#eee; border-radius:999px; padding:2px 8px; font-size:11px; color:#333; }}

/* Bigger tiles (single column) */
.grid {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}}
.grid img {{
  width: 100%;
  height: 330px;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid rgba(0,0,0,0.06);
}}
.tile {{
  height:330px; display:flex; align-items:center; justify-content:center; font-size:13px;
  color:#444; border:1px solid rgba(0,0,0,0.06); border-radius:10px; background:#f7f7f7; padding:10px; text-align:center;
}}

/* Selected highlight */
#gallery-grid img.selected, #gallery-grid .tile.selected {{
  outline: 3px solid #2b8a3e;
  box-shadow: 0 0 0 3px rgba(43,138,62,0.25);
}}

/* Move controls left; sidebar is on the right */
.leaflet-top.leaflet-left .leaflet-control, .leaflet-bottom.leaflet-left .leaflet-control {{
  margin-left: 12px;
}}

/* Hide attribution (be mindful of terms if publishing) */
.leaflet-control-attribution {{ display: none !important; }}

/* Remove Leaflet popup width cap for photo popups */
.leaflet-popup.photo-popup,
.leaflet-popup.photo-popup .leaflet-popup-content-wrapper,
.leaflet-popup.photo-popup .leaflet-popup-content {{
  max-width: none !important;
  width: auto !important;
}}

/* Fullscreen lightbox for original images */
#photo-overlay {{
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.8);
  display: none;         /* toggled via JS */
  align-items: center; justify-content: center;
  z-index: 10000;        /* above sidebar & map */
}}
#photo-overlay img {{
  max-width: 95vw; max-height: 95vh; /* <-- fixed typo: max-width */
  width: auto; height: auto;
  border-radius: 10px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}}
#photo-overlay .close {{
  position: absolute; top: 14px; right: 14px;
  background: rgba(255,255,255,0.9);
  border: 0; border-radius: 999px;
  padding: 8px 12px; font-size: 14px; cursor: pointer;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}
</style>
"""


# ---------------- Sidebar HTML ----------------
def _sidebar_html() -> str:
    return """
<div id="gallery-panel">
  <div id="gallery-header">
    <h3>Photos</h3>
    <div id="gallery-controls">
      <label><input type="checkbox" id="follow-map" checked/> Follow</label>
      <label><input type="checkbox" id="show-all"/> Show all</label>
      <button id="gallery-refresh">Refresh</button>
    </div>
  </div>
  <div id="gallery-count">
    Loaded: <span class="badge" id="total-count">0</span>
    <span style="margin-left:8px;">In view: <span class="badge" id="inview-count">0</span></span>
  </div>
  <div id="gallery-empty">Pan/zoom the map — photos within the current view will appear here.</div>
  <div class="grid" id="gallery-grid"></div>
</div>
"""


# ---------------- JS: viewport gallery + selection marker + overlay ----------------
_VIEWPORT_JS = """
<script>
(function(){
  function findMapVar(){ return Object.keys(window).find(k => k.startsWith("map_") && window[k] && typeof window[k].setView === "function"); }
  function getLeafletMap(){ const key = findMapVar(); return key ? window[key] : null; }
  function waitForMapAndInit(retries){
    const map = getLeafletMap();
    if (!map) { if (retries>0) return setTimeout(()=>waitForMapAndInit(retries-1),100); console.warn("[photo-map] Leaflet map not found."); return; }
    init(map);
  }

  // ---------- GLOBAL overlay (callable inline) ----------
  let overlay, overlayImg, overlayClose;
  function ensureOverlay(){
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'photo-overlay';
    overlay.innerHTML = '<button class="close" aria-label="Close">Close ✕</button><img alt="photo" />';
    document.body.appendChild(overlay);
    overlayImg = overlay.querySelector('img');
    overlayClose = overlay.querySelector('.close');
    function hide(){ overlay.style.display='none'; overlayImg.removeAttribute('src'); }
    overlay.addEventListener('click', (e)=>{ if (e.target===overlay || e.target===overlayClose) hide(); });
    document.addEventListener('keydown', (e)=>{ if (e.key==='Escape') hide(); });
    return overlay;
  }
  function openOverlay(src, title){
    ensureOverlay();
    overlayImg.alt = title || 'photo';
    overlayImg.src = src;
    overlay.style.display='flex';
  }
  window.__PHOTO_OPEN_ORIGINAL = function(src, title){ if (!src) return; openOverlay(src, title||''); };

  // ---------- selection state ----------
  let selectionLayer=null, selectionMarker=null, selectedId=null;
  function ensureSelectionLayer(map){ if(!selectionLayer) selectionLayer=L.layerGroup().addTo(map); return selectionLayer; }
  function featureId(f){
    if (!f) return null;
    const c=(f.geometry&&f.geometry.coordinates)||[], p=(f.properties&&(f.properties.path||f.properties.filename))||"";
    return [String(c[0]||""),String(c[1]||""),String(p||"")].join("|");
  }
  function clearSelectionHighlight(){ selectedId=null; document.querySelectorAll('#gallery-grid .tile, #gallery-grid img').forEach(el=>el.classList.remove('selected')); }
  function highlightTileById(id){ document.querySelectorAll('#gallery-grid [data-fid]').forEach(el=>{ if (el.getAttribute('data-fid')===id) el.classList.add('selected'); else el.classList.remove('selected'); }); }

  // ---------- robust visibility (avoid sidebar-covered area) ----------
  function visibleContainerBounds(map){
    const c = map.getContainer();
    const cw = c.clientWidth, ch = c.clientHeight;
    let visibleRight = cw; // default full width
    const sidebar = document.getElementById('gallery-panel');
    if (sidebar){
      const mr = c.getBoundingClientRect();
      const sr = sidebar.getBoundingClientRect();
      const overlapX = Math.max(0, Math.min(mr.right, sr.right) - Math.max(mr.left, sr.left));
      const overlapY = Math.max(0, Math.min(mr.bottom, sr.bottom) - Math.max(mr.top, sr.top));
      if (overlapY > 0 && overlapX > 0) visibleRight = Math.max(0, cw - overlapX);
    }
    return L.bounds(L.point(0,0), L.point(visibleRight, ch));
  }
  function isInVisibleViewport(map, lat, lon){
    const p = map.latLngToContainerPoint([lat, lon]);
    const b = visibleContainerBounds(map);
    return b.contains(p);
  }
  function featuresInViewport(map, features){
    const inside = [];
    (features||[]).forEach(f=>{ try{ const c=f.geometry&&f.geometry.coordinates; if(!c) return; const lat=c[1], lon=c[0]; if (isInVisibleViewport(map, lat, lon)) inside.push(f); }catch(e){} });
    return inside;
  }

  // ---------- thumb popup (click to open full overlay) ----------
  function escapeAttr(s){ return String(s||'').replace(/"/g,'&quot;'); }
  function thumbPopupHTML(props){
    const title = (props && (props.path || props.filename)) || "photo";
    const thumbSrc = (props && props.thumb) || null;      // THUMB ONLY in popup
    const fullSrc  = (props && props.img_rel) || null;     // ORIGINAL for overlay
    let html = '<div style="font-size:12px; text-align:center; max-width: 60vw;">';
    if (thumbSrc){
      if (fullSrc){
        html += '<img src="'+thumbSrc+'" alt="'+escapeAttr(title)+'" ' +
                'data-full="'+escapeAttr(fullSrc)+'" ' +
                'onclick="window.__PHOTO_OPEN_ORIGINAL(this.getAttribute(\\'data-full\\'), this.alt)" ' +
                'style="max-width: 520px; max-height: 400px; width:auto; height:auto; border-radius:10px; display:block; margin:0 auto 6px; cursor:zoom-in;" />';
        html += '<div style="font-size:11px; color:#555;">Click the image to view full size</div>';
      } else {
        html += '<img src="'+thumbSrc+'" alt="'+escapeAttr(title)+'" ' +
                'style="max-width: 520px; max-height: 400px; width:auto; height:auto; border-radius:10px; display:block; margin:0 auto 6px;" />';
      }
    } else {
      html += '<div style="padding:8px 0;color:#666;">No thumbnail available.</div>';
    }
    html += '<div>'+ (title || "") +'</div></div>';
    return html;
  }

  // ---------- marker placement (popup shows THUMB; click opens ORIGINAL overlay) ----------
  function placeSelectionMarker(map, lat, lon, props, fid){
    ensureSelectionLayer(map);
    if (selectionMarker){ try{ selectionLayer.removeLayer(selectionMarker); }catch(e){} selectionMarker=null; }

    selectionMarker = L.marker([lat, lon], {
      title: (props && (props.path || props.filename)) || "photo",
      icon: L.icon({
        iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-red.png",
        shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.3/images/marker-shadow.png",
        iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34]
      })
    });

    selectionMarker
      .addTo(selectionLayer)
      .bindPopup(thumbPopupHTML(props), {maxWidth: 560, keepInView: true, className: "photo-popup"})
      .openPopup();

    selectionMarker.on("popupclose", function(){ try{ selectionLayer.removeLayer(selectionMarker); }catch(e){} selectionMarker=null; clearSelectionHighlight(); });

    map.setView([lat, lon], Math.max(12, map.getZoom()), {animate: true});
    selectedId = fid || null; if (selectedId) highlightTileById(selectedId);
  }

  // ---------- gallery / filtering ----------
  function makeTextTile(text, fid, click){ const div=document.createElement('div'); div.className='tile'; div.setAttribute('data-fid', fid||''); div.textContent=text||'No preview'; if(click) div.onclick=click; return div; }
  function renderGallery(features){
    const grid=document.getElementById('gallery-grid');
    const empty=document.getElementById('gallery-empty');
    const inCount=document.getElementById('inview-count');
    grid.innerHTML=''; inCount.textContent=String(features.length||0);
    if(!features||!features.length){ if(empty) empty.style.display='block'; return; }
    if(empty) empty.style.display='none';

    const maxItems=120;
    features.slice(0,maxItems).forEach(f=>{
      const fid=featureId(f), props=f.properties||{}, alt=props.path||'photo';
      const coords=f.geometry&&f.geometry.coordinates;
      const thumbSrc = props.thumb; // thumbs ONLY in sidebar
      const click = function(){ const map=getLeafletMap(); if (!map || !coords || coords.length<2) return; placeSelectionMarker(map, coords[1], coords[0], props, fid); };

      if (thumbSrc){
        const img=document.createElement('img');
        img.src=thumbSrc; img.alt=alt; img.title=alt; img.setAttribute('data-fid', fid||'');
        img.onerror=function(){ const t=makeTextTile(alt,fid,click); img.replaceWith(t); if(selectedId===fid) t.classList.add('selected'); };
        img.onclick=click; if(selectedId===fid) img.classList.add('selected');
        grid.appendChild(img);
      } else {
        const t=makeTextTile(alt,fid,click); if(selectedId===fid) t.classList.add('selected'); grid.appendChild(t);
      }
    });
  }

  function bindMarkerPopups(map){
    try{
      map.eachLayer(function(layer){
        if (layer && typeof layer.eachLayer==='function'){
          layer.eachLayer(function(l){
            if(!l || !l.feature) return;
            const f=l.feature, fid=featureId(f), props=f.properties||{};
            l.bindPopup(thumbPopupHTML(props), {maxWidth:560, keepInView:true, className:"photo-popup"});
            l.on('popupopen', function(){ selectedId=fid; highlightTileById(selectedId); });
            l.on('popupclose', function(){ clearSelectionHighlight(); });
            l.on('click', function(){ const fullSrc = props && props.img_rel; if (fullSrc) window.__PHOTO_OPEN_ORIGINAL(fullSrc, props.path || props.filename); });
          });
        }
      });
    }catch(e){}
  }

  function recomputeAndRender(map, all, showAll){
    const feats = (showAll && showAll.checked) ? all : featuresInViewport(map, all);
    renderGallery(feats); if (selectedId) highlightTileById(selectedId);
  }

  function init(map){
    ensureSelectionLayer(map);
    const all=(window.__PHOTO_FEATURES__ && window.__PHOTO_FEATURES__.features) ? window.__PHOTO_FEATURES__.features : [];
    document.getElementById('total-count').textContent=String(all.length);

    const showAll=document.getElementById('show-all');
    const initial=(showAll && showAll.checked) ? all : featuresInViewport(map, all);
    renderGallery(initial);

    const follow=document.getElementById('follow-map');
    map.on('moveend', function(){ if (follow && follow.checked) recomputeAndRender(map, all, showAll); });

    const refreshBtn=document.getElementById('gallery-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', function(){ recomputeAndRender(map, all, showAll); });

    if (showAll) showAll.addEventListener('change', function(){ recomputeAndRender(map, all, showAll); });

    window.addEventListener('resize', function(){ recomputeAndRender(map, all, showAll); });

    bindMarkerPopups(map);
    console.debug("[photo-map] total features:", all.length);
  }

  waitForMapAndInit(30);
})();
</script>
"""


class MapBuilder:
    def __init__(self, default_zoom_start: int = 2):
        self.default_zoom_start = default_zoom_start

    def _initial_center(self, points: List[Tuple[float, float]]) -> Tuple[float, float]:
        if not points:
            return (20.0, 0.0)
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        return (sum(lats) / len(lats), sum(lons) / len(lons))

    def build_map(
        self,
        points: List[Tuple[float, float]],
        geojson_file: Optional[Path],
        out_html: Path,
        include_heat: bool = True,
        heat_min_opacity: float = 0.35,
        heat_radius: int = 16,
        heat_blur: int = 20,
        heat_max_zoom: int = 18,
        cluster: bool = True,
        point_radius: int = 6,
    ):
        center = self._initial_center(points)

        # Create map WITHOUT default tiles; we add multiple basemaps next
        fmap = folium.Map(
            location=center,
            tiles=None,
            zoom_start=self.default_zoom_start,
            control_scale=True,
        )

        # Inject CSS + sidebar
        fmap.get_root().html.add_child(folium.Element(_css_for(fmap.get_name())))
        fmap.get_root().html.add_child(folium.Element(_sidebar_html()))

        # Basemaps
        _add_basemaps(fmap, default_name=AppConfig().map_style.default)

        # Heat layer
        if include_heat and points:
            HeatMap(
                points,
                min_opacity=heat_min_opacity,
                radius=heat_radius,
                blur=heat_blur,
                max_zoom=heat_max_zoom,
                name="Heatmap",
            ).add_to(fmap)

        # GeoJSON points (and inject features for JS)
        if geojson_file and geojson_file.exists():
            text = geojson_file.read_text(encoding="utf-8")
            try:
                gj_data = json.loads(text)
            except Exception:
                gj_data = {"type": "FeatureCollection", "features": []}

            tooltip = None
            feats = gj_data.get("features") or []
            if feats:
                available = set()
                for f in feats:
                    props = (f or {}).get("properties") or {}
                    available |= set(props.keys())
                fields = [
                    f for f in ["path", "datetime", "make", "model"] if f in available
                ]
                if fields:
                    tooltip = folium.GeoJsonTooltip(
                        fields=fields,
                        aliases=["File" if f == "path" else f.title() for f in fields],
                        sticky=False,
                    )

            gj = folium.GeoJson(gj_data, name="Photo points", tooltip=tooltip)
            if cluster:
                mc = MarkerCluster(name="Clusters")
                mc.add_to(fmap)
                gj.add_to(mc)
            else:
                gj.add_to(fmap)

            fmap.get_root().html.add_child(
                folium.Element(
                    f"<script>window.__PHOTO_FEATURES__ = {json.dumps(gj_data)};</script>"
                )
            )
        else:
            fmap.get_root().html.add_child(
                folium.Element(
                    "<script>window.__PHOTO_FEATURES__ = {type:'FeatureCollection',features:[]};</script>"
                )
            )

        # Controls on the LEFT so the sidebar doesn't cover them
        MiniMap(toggle_display=True, position="bottomleft").add_to(fmap)
        Fullscreen(position="topleft").add_to(fmap)
        MeasureControl(position="topleft", primary_length_unit="kilometers").add_to(
            fmap
        )
        folium.LayerControl(position="topleft", collapsed=False).add_to(fmap)

        # Viewport-based gallery + selection marker logic
        fmap.get_root().html.add_child(folium.Element(_VIEWPORT_JS))

        # Fit bounds to points if any
        b = bounds_from_points(points)
        if b:
            (min_lat, min_lon, max_lat, max_lon) = b
            fmap.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

        out_html.parent.mkdir(parents=True, exist_ok=True)
        fmap.save(str(out_html))
        return out_html
