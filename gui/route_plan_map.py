"""路径规划地图交互：点击选点 + 途经点串联 + 实时路线展示（行者风格）。

核心流程：
1. 用户在地图上点击添加途经点（带数字序号标记）
2. 途经点列表实时更新，支持删除/清空
3. 点击「规划」按钮：拿途经点坐标 → 调高德 bicycling 逐段规划 → 拼接路线
4. 路线渲染在地图上（蓝色折线 + 起终点标记）
5. 规划完成后可转路书分析（复用 RouteDialog）

技术实现：QWebEngineView + QWebChannel（JS ↔ Python 双向通信）。
"""
import json
import logging

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

logger = logging.getLogger("fit.planmap")

# ── 交互式规划地图 HTML 模板 ──
# 点击地图添加途经点、途经点数字标记、路线折线渲染
_PLAN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<script>window._AMapSecurityConfig = { securityJsCode: '__SEC__' };</script>
<script src="https://webapi.amap.com/loader.js"></script>
<style>
html,body{margin:0;height:100%;background:#0f1115}
#map{height:100%}
.waypoint-info{position:fixed;bottom:8px;left:8px;background:rgba(0,0,0,0.7);color:#fff;padding:4px 10px;border-radius:4px;font-size:12px;display:none}
</style>
</head>
<body>
<div id="map"></div>
<div class="waypoint-info" id="waypointInfo"></div>
<script>
var map, waypoints = [], markers = [], routeLine = null;

function initMap() {
    document.body.setAttribute('data-status', 'loading');
    AMapLoader.load({ key: '__KEY__', version: '2.0' }).then(function() {
        document.body.setAttribute('data-status', 'loaded');
        map = new AMap.Map('map', { viewMode: '2D', zoom: 13, center: [116.397, 39.909] });
        map.on('click', function(e) {
            var lng = e.lnglat.getLng();
            var lat = e.lnglat.getLat();
            addWaypoint(lng, lat);
        });
        var info = document.getElementById('waypointInfo');
        info.style.display = 'block';
        info.textContent = '点击地图添加途经点，当前 ' + waypoints.length + ' 个点';
    }).catch(function(err) {
        document.body.setAttribute('data-status', 'error');
        document.body.innerHTML = '<div style="color:#ff9a9a;padding:14px">地图加载失败：' + (err.message || err) + '</div>';
    });
}

function addWaypoint(lng, lat) {
    var idx = waypoints.length + 1;
    waypoints.push({lng: lng, lat: lat});
    var content = '<div style="width:22px;height:22px;line-height:22px;text-align:center;'
        + 'border-radius:50%;background:#1e88e5;color:#fff;font-size:12px;font-weight:bold;'
        + 'border:2px solid #fff;box-shadow:0 0 0 2px rgba(30,136,229,.4)">' + idx + '</div>';
    var marker = new AMap.Marker({ position: [lng, lat], content: content, offset: [0, -11] });
    map.add(marker);
    markers.push(marker);
    var info = document.getElementById('waypointInfo');
    if (info) info.textContent = '点击地图添加途经点，当前 ' + waypoints.length + ' 个点';
}

function getWaypointsJSON() {
    return JSON.stringify(waypoints.map(function(w){ return [w.lng, w.lat]; }));
}

function clearWaypoints() {
    waypoints = [];
    markers.forEach(function(m) { map.remove(m); });
    markers = [];
    if (routeLine) { map.remove(routeLine); routeLine = null; }
    var info = document.getElementById('waypointInfo');
    if (info) info.textContent = '点击地图添加途经点，当前 0 个点';
}

function removeLastWaypoint() {
    if (waypoints.length === 0) return;
    waypoints.pop();
    var m = markers.pop();
    map.remove(m);
    if (routeLine) { map.remove(routeLine); routeLine = null; }
    var info = document.getElementById('waypointInfo');
    if (info) info.textContent = '点击地图添加途经点，当前 ' + waypoints.length + ' 个点';
}

function renderRoute(polylineCoords) {
    if (routeLine) { map.remove(routeLine); }
    routeLine = new AMap.Polyline({
        path: polylineCoords,
        strokeColor: '#1e88e5', strokeWeight: 5, strokeOpacity: 0.95,
        showDir: true, lineJoin: 'round', lineCap: 'round'
    });
    map.add(routeLine);
    if (polylineCoords.length > 0) {
        map.setFitView([routeLine], false, [40,40,40,40]);
    }
}

// 页面加载完成后初始化地图（轮询等待 AMapLoader 就绪）
(function waitForAMap() {
    if (window.AMapLoader) { initMap(); return; }
    setTimeout(waitForAMap, 200);
})();
</script>
</body>
</html>"""


class RoutePlanMapWidget(QWidget):
    """交互式地图组件：点击选点 + 途经点管理 + 路线渲染。

    通信方式：JS 完全独立运行（无 QWebChannel），Python 通过 runJavaScript
    读取 JS 变量 getWaypointsJSON() 获取途经点坐标。
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._key = (config.get("amap_key") or "").strip()
        self._sec = (config.get("amap_security") or "").strip()
        self._waypoints = []  # [(lng, lat), ...]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._web = QWebEngineView()
        try:
            s = self._web.settings()
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        except Exception:
            pass

        self._load_map()
        lay.addWidget(self._web)

    def _load_map(self):
        html = _PLAN_HTML.replace("__KEY__", self._key).replace("__SEC__", self._sec or "")
        self._web.setHtml(html, QUrl("file:///"))

    def refresh_waypoints(self, callback):
        """通过 runJavaScript 读取 JS 里存储的途经点坐标，回调 callback(points)。"""
        self._web.page().runJavaScript("getWaypointsJSON();", callback)

    def clear_waypoints(self):
        self._waypoints.clear()
        self._web.page().runJavaScript("clearWaypoints();")

    def remove_last(self):
        if self._waypoints:
            self._waypoints.pop()
        self._web.page().runJavaScript("removeLastWaypoint();")

    def render_route(self, coords):
        js = f"renderRoute({json.dumps(coords, ensure_ascii=False)});"
        self._web.page().runJavaScript(js)


class PlanDialog(QDialog):
    """路径规划对话框（行者风格）：左侧交互地图 + 右侧途经点列表。"""

    def __init__(self, config, ai_client_factory=None, ai_enabled=False, parent=None):
        super().__init__(parent)
        self.config = config
        self._ai_factory = ai_client_factory
        self._ai_enabled = ai_enabled
        self.setWindowTitle("路径规划（地图点击选点）")
        self.resize(960, 640)

        hlay = QHBoxLayout(self)

        # 左侧：地图
        self.map_widget = RoutePlanMapWidget(config, self)
        hlay.addWidget(self.map_widget, 3)

        # 右侧：途经点列表 + 操作
        right = QVBoxLayout()

        lbl = QLabel("<b>途经点列表</b>（点击地图添加）")
        right.addWidget(lbl)

        self.pt_list = QListWidget()
        right.addWidget(self.pt_list, 1)

        btn_row = QHBoxLayout()
        self.btn_undo = QPushButton("撤销上一个")
        self.btn_undo.clicked.connect(self._undo)
        self.btn_clear = QPushButton("清空全部")
        self.btn_clear.clicked.connect(self._clear)
        btn_row.addWidget(self.btn_undo)
        btn_row.addWidget(self.btn_clear)
        right.addLayout(btn_row)

        self.chk_enrich = QCheckBox("联网补全海拔（用于爬坡分析）")
        self.chk_enrich.setChecked(True)
        right.addWidget(self.chk_enrich)

        self.btn_plan = QPushButton("🧭 规划路线")
        self.btn_plan.setObjectName("primary")
        self.btn_plan.clicked.connect(self._plan)
        right.addWidget(self.btn_plan)

        self.btn_save = QPushButton("📋 转路书分析")
        self.btn_save.clicked.connect(self._save_route)
        self.btn_save.setEnabled(False)
        right.addWidget(self.btn_save)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        right.addWidget(self.status)

        hlay.addLayout(right, 1)

        self._route = None

        # 定时刷新途经点列表（每 1 秒从 JS 读取）
        from PySide6.QtCore import QTimer
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_waypoints)
        self._refresh_timer.start(1000)

    def _refresh_waypoints(self):
        """从 JS 读取途经点，更新右侧列表。"""
        self.map_widget.refresh_waypoints(self._on_waypoints_loaded)

    def _on_waypoints_loaded(self, json_str):
        """runJavaScript 回调：解析途经点 JSON 并更新列表。"""
        import json as _json
        try:
            pts = _json.loads(json_str or "[]")
        except Exception:
            return
        # 如果列表没变化，不刷新（避免闪烁）
        if pts == self._last_loaded_pts:
            return
        self._last_loaded_pts = pts
        self.pt_list.clear()
        for i, (lng, lat) in enumerate(pts, 1):
            self.pt_list.addItem(f"{i}.  {lng:.6f}, {lat:.6f}")

    _last_loaded_pts = []

    def _undo(self):
        self.map_widget.remove_last()

    def _clear(self):
        self.map_widget.clear_waypoints()
        self.pt_list.clear()
        self._route = None
        self.btn_save.setEnabled(False)

    def _plan(self):
        # 先读取最新途经点
        self.map_widget.refresh_waypoints(self._do_plan)

    def _do_plan(self, json_str):
        import json as _json
        try:
            pts = _json.loads(json_str or "[]")
        except Exception:
            pts = []
        if len(pts) < 2:
            QMessageBox.information(self, "提示", "请在地图上至少点击 2 个点（起点和终点）")
            return

        key = (self.config.get("amap_web_key") or "").strip()
        if not key:
            QMessageBox.information(self, "提示", "请先在「设置」中配置高德 Web服务 Key")
            return

        # 转为 (lng, lat) 元组
        pts = [(p[0], p[1]) for p in pts]
        self.btn_plan.setEnabled(False)
        self.status.setText("规划中…（逐段调高德骑行规划）")
        self.status.setStyleSheet("color: #888;")

        from PySide6.QtCore import QThread
        self._worker = _PlanWorker(key, pts, self.chk_enrich.isChecked(), self)
        self._worker.done.connect(self._on_plan_done)
        self._worker.start()

    def _on_plan_done(self, payload):
        self.btn_plan.setEnabled(True)
        if isinstance(payload, str):
            self.status.setText(payload)
            self.status.setStyleSheet("color: #c62828;")
            return

        self._route = payload
        self.status.setText(f"规划成功：{payload.get('total_distance_km')} km")
        self.status.setStyleSheet("")
        self.btn_save.setEnabled(True)

        # 渲染路线在地图上（用 GCJ-02 原始坐标，高德地图是 GCJ-02 坐标系）
        if self._route.get("gcj_points"):
            coords = self._route["gcj_points"]
        else:
            coords = [(p["lon"], p["lat"]) for p in self._route["points"]]
        self.map_widget.render_route(coords)

    def _save_route(self):
        if not self._route:
            return
        from gui.route_dialog import RouteDialog
        dlg = RouteDialog(self, ai_client_factory=self._ai_factory,
                          ai_enabled=self._ai_enabled)
        dlg.load_route(self._route)
        dlg.exec()


class _PlanWorker(QThread):
    done = Signal(object)

    def __init__(self, key, points, enrich, parent=None):
        super().__init__(parent)
        self._key = key
        self._points = points
        self._enrich = enrich

    def run(self):
        from core import route_plan
        try:
            r = route_plan.plan_route_with_waypoints(
                self._key, self._points, name="规划路线", enrich=self._enrich)
            self.done.emit(r)
        except Exception as e:
            self.done.emit(f"规划失败：{e}")