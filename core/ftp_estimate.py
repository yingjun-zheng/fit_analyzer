"""FTP 自动估算：从活动功率数据（真实功率或估算功率）计算最佳 20 分钟功率 × 0.95。

FTP（功能阈值功率）是训练负荷 / 区间分析的核心锚点。有功率计时用真实功率，
无功率计（如 iGPSPORT 码表）时用 estimate_power 估出的功率近似。

口径：
- 20 分钟最佳功率：滑动窗口取连续 20 分钟平均功率的最大值
- FTP ≈ 20 分钟最佳功率 × 0.95（经典经验系数）
- 附带功重比 W/kg = FTP / 骑手体重
"""


def best_20min_power(records, duration_s=1200):
    """计算最佳 N 分钟平均功率（默认 20 分钟）。

    records: 逐条记录（含 power 字段）；返回平均功率 W，点数不足返回 None。
    """
    powers = [r.get("power") for r in records if r.get("power") is not None]
    if len(powers) < 2:
        return None

    # 每条记录 ≈ 1 秒（fitparse 通常 1~3s 采样），用点数近似时间窗
    # 20 分钟 ≈ 1200 秒；若采样稀疏，按点数比例缩窗
    window = min(duration_s, len(powers))
    best = 0.0
    # 前缀和求最大滑动窗口平均
    prefix = [0.0]
    for p in powers:
        prefix.append(prefix[-1] + p)
    for i in range(len(prefix) - window):
        s = prefix[i + window] - prefix[i]
        avg = s / window
        if avg > best:
            best = avg
    return round(best, 1) if best > 0 else None


def estimate_ftp(records, config=None, power_multiplier=0.95):
    """估算 FTP。

    records: 逐条记录（无 power 字段时，先由调用方用 estimate_power 补全）。
    返回 dict：{ftp_w, best_20min_w, wkg}；无有效数据返回 None。
    """
    b20 = best_20min_power(records)
    if b20 is None:
        return None
    ftp = round(b20 * power_multiplier)
    rider_kg = float(config.get("power_rider_weight_kg", 70.0)) if config else 70.0
    wkg = round(ftp / rider_kg, 2) if rider_kg > 0 else None
    return {
        "ftp_w": ftp,
        "best_20min_w": b20,
        "wkg": wkg,
    }


def ftp_text(records, config=None):
    """返回 FTP 估算的纯文本描述（供展示/提示）。"""
    est = estimate_ftp(records, config)
    if not est:
        return "无有效功率数据，无法估算 FTP。"
    lines = [
        f"最佳 20 分钟功率：{est['best_20min_w']} W",
        f"估算 FTP：{est['ftp_w']} W",
    ]
    if est["wkg"] is not None:
        lines.append(f"功重比：{est['wkg']} W/kg")
    return "，".join(lines)
