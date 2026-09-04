"""骑行天气查询与建议：调高德天气 API，输出温度/风力/湿度 + 骑行穿搭/安全建议。

复用 fit_analyzer 的高德 Web服务 key（与路径规划/POI 搜索共用同一个 key）。
"""
import urllib.parse
from . import http_utils

_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"


def get_weather(key, city="北京"):
    """查询城市天气，返回 {province, city, weather, temperature, windpower, humidity, ...}。"""
    params = urllib.parse.urlencode({
        "key": key,
        "city": city,
        "extensions": "base",
    })
    url = f"{_WEATHER_URL}?{params}"
    status, obj = http_utils.http_json(url, timeout=15)
    if status != 200 or not isinstance(obj, dict) or obj.get("status") != "1":
        return None
    lives = obj.get("lives") or []
    if not lives:
        return None
    return lives[0]


def _parse_windpower(windpower):
    """解析风力字符串（如 '≤3'、'3-4'），返回数值。"""
    if not windpower:
        return None
    try:
        w = windpower.strip().replace("≤", "").replace("<=", "")
        if "-" in w:
            a, b = w.split("-", 1)
            return (float(a) + float(b)) / 2.0
        return float(w)
    except (ValueError, TypeError):
        return None


def ride_suggestion(weather_data):
    """根据天气数据生成骑行建议（移植自 zride 的 WeatherService.getSuggest 逻辑）。

    weather_data: get_weather 返回的 dict。
    返回 dict：{temperature, weather, windpower, humidity, suggestion_lines[]}。
    """
    if not weather_data:
        return {"error": "无法获取天气信息"}

    temp_str = weather_data.get("temperature")
    windpower_str = weather_data.get("windpower")
    humidity_str = weather_data.get("humidity")

    suggestions = []

    # 温度分级建议
    if temp_str is not None:
        try:
            temp = float(temp_str)
        except (ValueError, TypeError):
            temp = None
        if temp is not None:
            if temp <= 10:
                suggestions.append("气温较低，建议穿着厚外套、长裤和保暖骑行手套。")
            elif temp <= 15:
                suggestions.append("气温适中，建议穿着薄外套和长裤，注意防风。")
            elif temp <= 20:
                suggestions.append("气温适宜，穿着骑行服或运动衫即可。")
            elif temp <= 28:
                suggestions.append("气温较高，建议穿着轻薄透气的骑行服，注意防晒和及时补水。")
            else:
                suggestions.append("气温炎热，避免正午骑行，穿着透气骑行服，做好防晒，及时补水。")

    # 风力分级建议
    if windpower_str is not None:
        wind = _parse_windpower(windpower_str)
        if wind is not None:
            if wind <= 2:
                suggestions.append("风力微弱，非常适合骑行。")
            elif wind <= 4:
                suggestions.append("风力适中，适合骑行，注意保持平衡。")
            elif wind <= 6:
                suggestions.append("风力较大，骑行有一定难度，建议降低车速，注意安全。")
            else:
                suggestions.append("风力强劲，不建议骑行。")

    # 湿度/降雨提醒
    if humidity_str is not None:
        try:
            humidity = float(humidity_str)
        except (ValueError, TypeError):
            humidity = None
        if humidity is not None and humidity >= 80:
            suggestions.append("当前区域湿度较大，近几小时可能有降雨，自行判断骑行条件。")

    return {
        "province": weather_data.get("province"),
        "city": weather_data.get("city"),
        "weather": weather_data.get("weather"),
        "temperature": temp_str,
        "windpower": windpower_str,
        "winddirection": weather_data.get("winddirection"),
        "humidity": humidity_str,
        "suggestion": "".join(suggestions) if suggestions else "天气数据正常，可正常骑行。",
        "suggestion_lines": suggestions,
    }