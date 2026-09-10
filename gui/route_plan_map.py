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

# WGS-84 → GCJ-02 前端纠偏 JS：与轨迹页（amap_track.py）共用同一段实现，
# 用于把本地数据库的 WGS-84 起点坐标转换到高德 GCJ-02 地图上。
from gui.amap_track import _WGS2GCJ as _WGS2GCJ_JS

# ── 交互式规划地图 HTML 模板 ──
# 点击地图添加途经点、途经点数字标记、路线折线渲染
_PLAN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<script>window._AMapSecurityConfig = { securityJsCode: '__SEC__' };</script>
<script>__WGS__</script>
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
var INIT_CENTER = __CENTER__;  // 最近骑行起点（WGS-84 [lng,lat]）；null 时用默认北京视野

function initMap() {
    document.body.setAttribute('data-status', 'loading');
    AMapLoader.load({ key: '__KEY__', version: '2.0' }).then(function() {
        document.body.setAttribute('data-status', 'loaded');
        var c = INIT_CENTER ? wgs84ToGcj02(INIT_CENTER[0], INIT_CENTER[1]) : [116.397, 39.909];
        map = new AMap.Map('map', { viewMode: '2D', zoom: 13, center: c });
        map.on('click', function(e) {
            var lng = e.lnglat.getLng();
            var lat = e.lnglat.getLat();
            addWaypoint(lng, lat);
        });
        var info = document.getElementById('waypointInfo');
        info.style.display = 'block';
        infoText();
    }).catch(function(err) {
        document.body.setAttribute('data-status', 'error');
        document.body.innerHTML = '<div style="color:#ff9a9a;padding:14px">地图加载失败：' + (err.message || err) + '</div>';
    });
}

function infoText() {
    var info = document.getElementById('waypointInfo');
    if (info) info.textContent = '点击地图加点 · 拖拽标记移位 · 右键标记删除 · 当前 ' + waypoints.length + ' 个点（首点=起点，末点=终点）';
}

function markerContent(i) {
    // 角色视觉：首点=绿「起」，末点=红「终」，中间=蓝色序号（单点按起点显示）
    var first = (i === 0), last = (i === waypoints.length - 1 && waypoints.length > 1);
    if (first) {
        return '<div style="width:24px;height:24px;line-height:24px;text-align:center;border-radius:50%;'
            + 'background:#2e7d32;color:#fff;font-size:11px;font-weight:bold;border:2px solid #fff;'
            + 'box-shadow:0 0 0 2px rgba(46,125,50,.4)">起</div>';
    }
    if (last) {
        return '<div style="width:24px;height:24px;line-height:24px;text-align:center;border-radius:50%;'
            + 'background:#c62828;color:#fff;font-size:11px;font-weight:bold;border:2px solid #fff;'
            + 'box-shadow:0 0 0 2px rgba(198,40,40,.4)">终</div>';
    }
    return '<div style="width:22px;height:22px;line-height:22px;text-align:center;border-radius:50%;'
        + 'background:#1e88e5;color:#fff;font-size:12px;font-weight:bold;border:2px solid #fff;'
        + 'box-shadow:0 0 0 2px rgba(30,136,229,.4)">' + (i + 1) + '</div>';
}

function bindMarkerEvents(marker, i) {
    // 高德 JS 2.0 已移除 1.4 的全局事件对象，事件统一用实例 .on() 绑定
    marker.on('dragend', function() {
        var p = marker.getPosition();  // 拖拽结束取标记自身位置，不依赖事件参数结构
        updateWaypointPos(i, p.getLng(), p.getLat());
    });
    marker.on('rightclick', function() {
        removeWaypointAt(i);
    });
}

// 全量重建标记（角色/序号可能因增删重排而变化；点数少，重建开销可忽略）
function rebuildMarkers() {
    markers.forEach(function(m) { map.remove(m); });
    markers = [];
    waypoints.forEach(function(w, i) {
        var marker = new AMap.Marker({
            position: [w.lng, w.lat],
            content: markerContent(i),
            offset: [0, -12],
            draggable: true
        });
        bindMarkerEvents(marker, i);
        map.add(marker);
        markers.push(marker);
    });
    infoText();
}

function addWaypoint(lng, lat) {
    waypoints.push({lng: lng, lat: lat});
    rebuildMarkers();
}

function getWaypointsJSON() {
    return JSON.stringify(waypoints.map(function(w){ return [w.lng, w.lat]; }));
}

function clearWaypoints() {
    waypoints = [];
    markers.forEach(function(m) { map.remove(m); });
    markers = [];
    if (routeLine) { map.remove(routeLine); routeLine = null; }
    infoText();
}

function removeLastWaypoint() {
    if (waypoints.length === 0) return;
    waypoints.pop();
    if (routeLine) { map.remove(routeLine); routeLine = null; }
    rebuildMarkers();
}

function removeWaypointAt(i) {
    if (i < 0 || i >= waypoints.length) return;
    waypoints.splice(i, 1);
    if (routeLine) { map.remove(routeLine); routeLine = null; }
    rebuildMarkers();
}

function moveWaypointToStart(i) {
    if (i <= 0 || i >= waypoints.length) return;
    var p = waypoints.splice(i, 1)[0];
    waypoints.unshift(p);
    if (routeLine) { map.remove(routeLine); routeLine = null; }
    rebuildMarkers();
}

function moveWaypointToEnd(i) {
    if (i < 0 || i >= waypoints.length - 1) return;
    var p = waypoints.splice(i, 1)[0];
    waypoints.push(p);
    if (routeLine) { map.remove(routeLine); routeLine = null; }
    rebuildMarkers();
}

function updateWaypointPos(i, lng, lat) {
    if (i < 0 || i >= waypoints.length) return;
    waypoints[i] = {lng: lng, lat: lat};
    if (routeLine) { map.remove(routeLine); routeLine = null; }
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


def build_plan_html(key, sec, init_center=None):
    """生成路径规划地图 HTML。

    init_center: WGS-84 [lng, lat]（如本地数据库里最近骑行的起点），
    前端用纠偏 JS 转成 GCJ-02 后作为地图初始视野；None 时用默认北京视野。
    提取为独立函数便于离屏测试（不依赖 QWebEngineView）。
    """
    return (_PLAN_HTML
            .replace("__KEY__", key or "")
            .replace("__SEC__", sec or "")
            .replace("__WGS__", _WGS2GCJ_JS)
            .replace("__CENTER__", json.dumps(init_center)))


class RoutePlanMapWidget(QWidget):
    """交互式地图组件：点击选点 + 途经点管理 + 路线渲染。

    通信方式：JS 完全独立运行（无 QWebChannel），Python 通过 runJavaScript
    读取 JS 变量 getWaypointsJSON() 获取途经点坐标。
    """

    def __init__(self, config, parent=None, init_center=None):
        super().__init__(parent)
        self.config = config
        self._key = (config.get("amap_key") or "").strip()
        self._sec = (config.get("amap_security") or "").strip()
        self._init_center = init_center  # WGS-84 [lng, lat] 或 None
        # 途经点唯一真源在 JS 侧（waypoints 数组），Python 只通过 runJavaScript 读写

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
        self._web.setHtml(build_plan_html(self._key, self._sec, self._init_center),
                          QUrl("file:///"))

    def refresh_waypoints(self, callback):
        """通过 runJavaScript 读取 JS 里存储的途经点坐标，回调 callback(points)。"""
        self._web.page().runJavaScript("getWaypointsJSON();", callback)

    def clear_waypoints(self):
        self._web.page().runJavaScript("clearWaypoints();")

    def remove_last(self):
        self._web.page().runJavaScript("removeLastWaypoint();")

    def remove_point(self, index):
        """删除第 index 个途经点（JS 侧重排序号并重建标记）。"""
        self._web.page().runJavaScript(f"removeWaypointAt({int(index)});")

    def move_point_to_start(self, index):
        """把第 index 个点移到首位（设为起点）。"""
        self._web.page().runJavaScript(f"moveWaypointToStart({int(index)});")

    def move_point_to_end(self, index):
        """把第 index 个点移到末位（设为终点）。"""
        self._web.page().runJavaScript(f"moveWaypointToEnd({int(index)});")

    def render_route(self, coords):
        js = f"renderRoute({json.dumps(coords, ensure_ascii=False)});"
        self._web.page().runJavaScript(js)


class PlanDialog(QDialog):
    """路径规划对话框（行者风格）：左侧交互地图 + 右侧途经点列表。"""

    def __init__(self, config, ai_client_factory=None, ai_enabled=False, parent=None, db=None):
        super().__init__(parent)
        self.config = config
        self._ai_factory = ai_client_factory
        self._ai_enabled = ai_enabled
        self.setWindowTitle("路径规划（地图点击选点）")
        self.resize(960, 640)

        # 定位到最近一次骑行的 GPS 起点：纯本地数据，不发起任何定位/联网请求
        init_center = None
        if db is not None:
            pos = db.latest_position()
            if pos:
                init_center = [pos["lon"], pos["lat"]]

        hlay = QHBoxLayout(self)

        # 左侧：地图
        self.map_widget = RoutePlanMapWidget(config, self, init_center=init_center)
        hlay.addWidget(self.map_widget, 3)

        # 右侧：途经点列表 + 操作
        right = QVBoxLayout()

        lbl = QLabel("<b>途经点列表</b>（地图点击添加 · 拖拽标记移位 · 右键标记删除）")
        right.addWidget(lbl)

        self.pt_list = QListWidget()
        self.pt_list.setToolTip("选中一个点后可删除，或设为起点/终点")
        right.addWidget(self.pt_list, 1)

        btn_row = QHBoxLayout()
        self.btn_undo = QPushButton("撤销上一个")
        self.btn_undo.clicked.connect(self._undo)
        self.btn_clear = QPushButton("清空全部")
        self.btn_clear.clicked.connect(self._clear)
        btn_row.addWidget(self.btn_undo)
        btn_row.addWidget(self.btn_clear)
        right.addLayout(btn_row)

        edit_row = QHBoxLayout()
        self.btn_del_sel = QPushButton("删除选中")
        self.btn_del_sel.clicked.connect(self._delete_selected)
        self.btn_to_start = QPushButton("设为起点")
        self.btn_to_start.clicked.connect(self._to_start)
        self.btn_to_end = QPushButton("设为终点")
        self.btn_to_end.clicked.connect(self._to_end)
        edit_row.addWidget(self.btn_del_sel)
        edit_row.addWidget(self.btn_to_start)
        edit_row.addWidget(self.btn_to_end)
        right.addLayout(edit_row)

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

        if init_center:
            self.status.setText("地图已定位到你最近一次骑行的 GPS 起点（本地数据，不联网）")

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

    def _selected_index(self):
        """当前列表选中点的序号；未选中返回 None 并提示。"""
        row = self.pt_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在途经点列表中选中一个点")
            return None
        return row

    def _delete_selected(self):
        idx = self._selected_index()
        if idx is not None:
            self.map_widget.remove_point(idx)

    def _to_start(self):
        idx = self._selected_index()
        if idx is not None:
            self.map_widget.move_point_to_start(idx)

    def _to_end(self):
        idx = self._selected_index()
        if idx is not None:
            self.map_widget.move_point_to_end(idx)

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