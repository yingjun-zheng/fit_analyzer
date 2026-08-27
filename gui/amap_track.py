"""轨迹地图面板（高德在线地图 / 固定图片背景 自动切换）。

设计要点：
- 默认（未配置高德 Key 或环境无 QWebEngineView）：沿用原「固定图片背景 + QPainter 轨迹」
  （TrackWidget），并在最底部小字提示用户去设置里配置 Key。
- 配置了高德 Key 且环境支持 QWebEngineView：用高德 JS API 2.0 渲染真实在线地图轨迹
  （仅基础轨迹线 + 起终点标记，不做海拔剖面等额外 UI）。

高德 Key 为「Web端(JS API)」类型，必须经网页（QWebEngineView）加载，因此用内嵌 AMap HTML
的方式。QWebEngineView 为可选依赖：导入失败时不报错，自动回退到图片背景轨迹。
"""
import json
import logging

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from gui.track_widget import TrackWidget

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineSettings

    _HAS_WEBENGINE = True
except Exception:  # 环境无 WebEngine（如精简打包）时优雅降级
    QWebEngineView = None
    QWebEngineSettings = None
    _HAS_WEBENGINE = False

logger = logging.getLogger("fit.trackmap")

# WGS-84 → GCJ-02（国测局加密），前端纠偏，与多数开源实现一致。
_WGS2GCJ = r"""
function outOfChina(lng, lat){return !(lng>73.66&&lng<135.05&&lat>3.86&&lat<53.55);}
function tLat(lng,lat){var r=-100+2*lng+3*lat+0.2*lat*lat+0.1*lng*lat+0.2*Math.sqrt(Math.abs(lng));r+=(20*Math.sin(6*lng*Math.PI)+20*Math.sin(2*lng*Math.PI))*2/3;r+=(20*Math.sin(lat*Math.PI)+40*Math.sin(lat/3*Math.PI))*2/3;r+=(160*Math.sin(lat/12*Math.PI)+320*Math.sin(lat*Math.PI/30))*2/3;return r;}
function tLng(lng,lat){var r=300+lng+2*lat+0.1*lng*lng+0.1*lng*lat+0.1*Math.sqrt(Math.abs(lng));r+=(20*Math.sin(6*lng*Math.PI)+20*Math.sin(2*lng*Math.PI))*2/3;r+=(20*Math.sin(lng*Math.PI)+40*Math.sin(lng/3*Math.PI))*2/3;r+=(150*Math.sin(lng/12*Math.PI)+300*Math.sin(lng/30*Math.PI))*2/3;return r;}
function wgs84ToGcj02(lng,lat){if(outOfChina(lng,lat))return [lng,lat];var dLat=tLat(lng-105,lat-35);var dLng=tLng(lng-105,lat-35);var radLat=lat/180*Math.PI;var magic=Math.sin(radLat);magic=1-0.00669342162296594323*magic*magic;var sq=Math.sqrt(magic);dLat=(dLat*180)/((6378245.0*(1-0.00669342162296594323))/(magic*sq)*Math.PI);dLng=(dLng*180)/(6378245.0/sq*Math.cos(radLat)*Math.PI);return [lng+dLng,lat+dLat];}
"""

# 自包含 HTML 模板：用占位符替换，避免 f-string 的花括号转义问题。
_HTML_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<script>window._AMapSecurityConfig = { securityJsCode: '__SECURITY__' };</script>
<script src="https://webapi.amap.com/loader.js"></script>
<style>html,body{margin:0;height:100%;background:#0f1115}#map{height:100%}</style>
</head>
<body>
<div id="map"></div>
<script>
__WGS__
var PTS = __DATA__;
function renderTrack(){
  AMapLoader.load({ key: '__KEY__', version: '2.0' }).then(function(){
    var map = new AMap.Map('map', { viewMode: '2D', zoom: 13 });
    var path = PTS.map(function(p){ var g = wgs84ToGcj02(p.lon, p.lat); return [g[0], g[1]]; });
    if(!path.length){ document.body.innerHTML = '<div style="color:#ff9a9a;padding:14px">该活动无 GPS 轨迹</div>'; return; }
    var line = new AMap.Polyline({ path: path, strokeColor: '#1e88e5', strokeWeight: 5, strokeOpacity: 0.95, showDir: true, lineJoin: 'round', lineCap: 'round' });
    map.add(line);
    var s = path[0], e = path[path.length - 1];
    map.add(new AMap.Marker({ position: s, content: '<div style=\\"width:14px;height:14px;border-radius:50%;background:#22c55e;border:2px solid #fff;box-shadow:0 0 0 2px rgba(34,197,94,.4)\\"></div>', offset: new AMap.Pixel(-7,-7) }));
    map.add(new AMap.Marker({ position: e, content: '<div style=\\"width:14px;height:14px;border-radius:50%;background:#ef4444;border:2px solid #fff;box-shadow:0 0 0 2px rgba(239,68,68,.4)\\"></div>', offset: new AMap.Pixel(-7,-7) }));
    map.setFitView([line], false, [40,40,40,40]);
  }).catch(function(err){ document.body.innerHTML = '<div style="color:#ff9a9a;padding:14px">地图加载失败：' + ((err && err.message) || err) + '</div>'; });
}
if(window.AMapLoader){ renderTrack(); } else { window.addEventListener('load', renderTrack); }
</script>
</body>
</html>"""


def build_amap_html(key, security, points):
    """生成自包含的高德地图 HTML（内联轨迹点 + 前端纠偏，无需外部文件）。"""
    pts = [
        {"lat": p[0], "lon": p[1]}
        for p in (points or [])
        if len(p) >= 2 and p[0] is not None and p[1] is not None
    ]
    data = json.dumps(pts, ensure_ascii=False)
    html = (
        _HTML_TPL
        .replace("__SECURITY__", security or "")
        .replace("__KEY__", key or "")
        .replace("__DATA__", data)
        .replace("__WGS__", _WGS2GCJ)
    )
    return html


class TrackMapPanel(QWidget):
    """轨迹页容器：根据配置自动在「在线地图」与「图片背景轨迹」间切换。"""

    def __init__(self, config, bg_path, parent=None):
        super().__init__(parent)
        self.config = config
        self._has_web = _HAS_WEBENGINE
        self._map = None
        self._points = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.stack = QStackedWidget()
        self.image_w = TrackWidget(bg_path or "")
        self.stack.addWidget(self.image_w)

        self.info_label = QLabel("")
        self.info_label.setObjectName("muted")
        self.info_label.setWordWrap(True)

        self.reminder = QLabel("")
        self.reminder.setObjectName("muted")
        self.reminder.setWordWrap(True)

        lay.addWidget(self.stack, 1)
        lay.addWidget(self.info_label)
        lay.addWidget(self.reminder)

    def _ensure_map(self):
        if self._map is None and self._has_web:
            self._map = QWebEngineView()
            # setHtml + file:// 基址时，须允许本地页面加载远程脚本/瓦片（默认禁）
            s = self._map.settings()
            try:
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            self.stack.addWidget(self._map)

    def set_track(self, points, bg_path=None, info=None):
        self._points = list(points or [])
        key = (self.config.get("amap_key") or "").strip()
        sec = (self.config.get("amap_security") or "").strip()

        if bg_path:
            self.image_w.set_background(bg_path)
        self.image_w.set_track(points)
        self.info_label.setText(info or "")

        use_map = bool(key) and self._has_web and len(self._points) >= 2
        if use_map:
            self._ensure_map()
            try:
                html = build_amap_html(key, sec, points)
                self._map.setHtml(html, QUrl("file:///"))
                self.stack.setCurrentWidget(self._map)
                self.reminder.setText("高德地图（在线）· 真实地图轨迹（已使用配置 Key）")
                return
            except Exception as e:
                logger.warning("高德地图渲染失败，回退图片背景：%s", e)

        # 回退 / 未配置：保留原图片背景轨迹
        self.stack.setCurrentWidget(self.image_w)
        if not key:
            self.reminder.setText(
                "未配置高德地图 Key，当前为示意轨迹（固定背景图）。设置 → 高德地图 可启用真实地图。"
            )
        elif not self._has_web:
            self.reminder.setText(
                "已配置 Key，但当前环境缺少 PySide6 WebEngine 组件，暂用示意轨迹（需安装/打包 PySide6 WebEngine）。"
            )
        else:
            self.reminder.setText("")
