"""配置模块：区间阈值、AI、地图等（JSON 持久化）。"""
import json
import threading
from pathlib import Path

DEFAULTS = {
    "app_name": "骑行FIT数据分析器",
    "version": "1.0.0",
    # ---- 统计区间 ----
    "hr_zone_pcts": [0.6, 0.7, 0.8, 0.9],      # 心率区间边界（最大心率百分比）：5 区
    "hr_max_override": 0,                        # 0 = 用数据内最大心率
    "speed_zone_kmh": [10, 15, 20, 25, 30, 35],  # 速度区间边界（km/h）：7 区
    "cadence_zone_rpm": [60, 70, 80, 90, 100],   # 踏频区间边界（rpm）：6 区
    # ---- AI ----
    "ai_enabled": False,
    "ai_base_url": "http://127.0.0.1:11434/v1",
    "ai_api_key": "",
    "ai_model": "qwen3.5-4b:latest",
    "ai_temperature": 0.4,
    "ai_timeout": 120,
    # ---- 其他 ----
    "track_max_points": 2000,
    # 设备型号表（用户可扩展）：{"厂商/产品码": "型号名"}，如 {"bryton/1801": "百锐腾 Rider 15"}
    "device_models": {},
    # ---- 功率估算 ----
    "power_rider_weight_kg": 70.0,   # 骑手体重(kg)
    "power_bike_weight_kg": 10.0,    # 自行车重量(kg)
    "power_crr": 0.005,              # 滚动阻力系数（公路车胎≈0.005）
    "power_cda": 0.35,               # 风阻面积(m²)（非气动姿势≈0.35）
    "power_air_density": 1.225,      # 空气密度(kg/m³)（海平面≈1.225）
    # ---- 训练负荷（TSS/CTL/ATL/TSB）----
    "ftp_w": 0,                      # 功能阈值功率(W)；0=未设置，训练负荷计算将尝试心率/功率估算法
    # ---- 高德地图（在线轨迹地图，可选） ----
    # amap_key 须为「Web端(JS API)」类型；amap_security 为对应的安全密钥(securityJsCode)
    "amap_key": "",
    "amap_security": "",
    # ---- 高德路径规划（可选） ----
    # amap_web_key 须为「Web服务」类型（不同于上面的 JS API key），用于骑行路径规划
    "amap_web_key": "",
}

_SENSITIVE = {"ai_api_key", "amap_security", "amap_web_key"}


class Config:
    def __init__(self, path: Path):
        self.path = path
        self.data = dict(DEFAULTS)
        self._lock = threading.Lock()
        self.load()

    def load(self):
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    user = json.load(f)
                if isinstance(user, dict):
                    self.data.update({k: v for k, v in user.items() if k in DEFAULTS})
        except Exception:
            pass

    def save(self):
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                tmp.replace(self.path)
            except Exception:
                pass

    def get(self, key, default=None):
        return self.data.get(key, default if default is not None else DEFAULTS.get(key))

    def set(self, key, value):
        if key in DEFAULTS:
            with self._lock:
                self.data[key] = value
            self.save()

    def update(self, d: dict):
        changed = False
        with self._lock:
            for k, v in d.items():
                if k in DEFAULTS and v is not None:
                    if k in _SENSITIVE and v == "******":
                        continue
                    self.data[k] = v
                    changed = True
        if changed:
            self.save()

    def public_dict(self):
        out = dict(self.data)
        for k in _SENSITIVE:
            if out.get(k):
                out[k] = "******"
        return out
