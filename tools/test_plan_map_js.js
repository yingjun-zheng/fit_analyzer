// 路径规划地图 JS 逻辑测试（node 版）：stub AMap，对业务 <script> 做数据逻辑断言。
// 用法：先由 python 生成 tools/out/plan_test.html，再 node tools/test_plan_map_js.js
const fs = require("fs");
const path = require("path");

const htmlPath = path.join(__dirname, "out", "plan_test.html");
const html = fs.readFileSync(htmlPath, "utf8");

// 提取全部内联 <script>（securityConfig / WGS 转换 / 业务逻辑）
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
if (scripts.length < 3) { console.error("FAIL: 内联 script 数量不对:", scripts.length); process.exit(1); }

// stub 运行环境
global.window = global;
global.document = { getElementById: () => null, body: { setAttribute() {}, innerHTML: "" } };
window.AMap = function () {};
// 与真实 AMap 2.0 一致：无 AMap.event，事件走实例 .on()（曾因 stub 了 1.4 的 AMap.event 而漏过该 bug）
window.AMap.Marker = function (opts) {
  this.position = opts.position; this.content = opts.content;
  this.draggable = opts.draggable; this.offset = opts.offset;
  this._handlers = {};
  this.on = (ev, fn) => { (window._bound = window._bound || []).push(ev); (this._handlers[ev] = this._handlers[ev] || []).push(fn); };
};
window.AMap.Polyline = function (opts) { this.opts = opts; };
window.setTimeout = () => 0; // 干掉 waitForAMap 轮询

// 执行全部内联脚本（var map 提升后为 undefined，函数调用前再赋值 stub）
const code = scripts.join("\n");
eval(code);
map = { add() {}, remove() {}, on() {}, setFitView() {} };

let ok = true;
function check(name, cond) {
  console.log(`  [${cond ? "PASS" : "FAIL"}] ${name}`);
  if (!cond) ok = false;
}
const same = (a, b) => Math.abs(a - b) < 1e-9;

// 1) 加 4 个点
addWaypoint(116.0, 39.0); addWaypoint(116.1, 39.1); addWaypoint(116.2, 39.2); addWaypoint(116.3, 39.3);
let pts = JSON.parse(getWaypointsJSON());
check("加 4 个点", pts.length === 4 && same(pts[0][0], 116.0));

// 2) 拖拽更新（模拟 dragend）
updateWaypointPos(2, 116.22, 39.22);
pts = JSON.parse(getWaypointsJSON());
check("拖拽更新第 3 点坐标", same(pts[2][0], 116.22) && same(pts[2][1], 39.22));

// 3) 设为起点（第 3 点 → 首位）
moveWaypointToStart(2);
pts = JSON.parse(getWaypointsJSON());
check("设为起点（重排到首位）", same(pts[0][0], 116.22) && pts.length === 4);

// 4) 设为终点（第 0 点 → 末位）
moveWaypointToEnd(0);
pts = JSON.parse(getWaypointsJSON());
check("设为终点（重排到末位）", same(pts[3][0], 116.22) && pts[0][0] === 116.0);

// 5) 删除第 2 个点（右键删除）
removeWaypointAt(1);
pts = JSON.parse(getWaypointsJSON());
check("删除任意点（剩 3 个）", pts.length === 3 && pts[0][0] === 116.0 && pts[1][0] === 116.3);

// 6) 撤销上一个
removeLastWaypoint();
pts = JSON.parse(getWaypointsJSON());
check("撤销上一个（剩 2 个）", pts.length === 2);

// 7) 清空
clearWaypoints();
check("清空全部", JSON.parse(getWaypointsJSON()).length === 0);

// 8) 边界：空列表操作不抛错
let boundary = "ok";
try { removeWaypointAt(0); moveWaypointToStart(0); moveWaypointToEnd(0); } catch (e) { boundary = "err:" + e; }
check("空列表操作不抛错", boundary === "ok");

// 9) 标记内容：起/终/序号
addWaypoint(116.0, 39.0); addWaypoint(116.1, 39.1); addWaypoint(116.2, 39.2);
check("首点标记含「起」", markerContent(0).includes("起") && markerContent(0).includes("#2e7d32"));
check("中间点标记含序号 2", markerContent(1).includes(">2<") && markerContent(1).includes("#1e88e5"));
check("末点标记含「终」", markerContent(2).includes("终") && markerContent(2).includes("#c62828"));

// 10) 标记绑定 dragend + rightclick，且可拖拽
window._bound = [];
rebuildMarkers();
check("标记绑定 dragend+rightclick", window._bound.includes("dragend") && window._bound.includes("rightclick"));
check("标记 draggable=true", markers.every(m => m.draggable === true));

// 11) 角色跟随重排变化：把中间点设为终点后，旧末点变中间序号
moveWaypointToEnd(1);
check("重排后标记角色刷新", markerContent(2).includes("终") && markerContent(0).includes("起") && markerContent(1).includes(">2<"));

// 12) 防回归：业务 JS 不得引用 AMap.event（1.4 专属 API，2.0 已移除——曾导致标记全部不显示）
check("业务 JS 无 AMap.event（1.4 API）", !scripts.some(s => s.includes("AMap.event")));

console.log(`\nJS 逻辑测试: ${ok ? "全部通过" : "存在失败"}`);
process.exit(ok ? 0 : 1);
