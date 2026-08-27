"""OCR 运行器（供 DSH 插件调用）：输入图片路径，输出 JSON 到 stdout。

用法: python ocr_runner.py <图片路径>
输出: {"lines": [...], "items": [{"text","x","y","w","h","score"}], "overlaps": [...]}
"""
import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "缺少图片路径"}, ensure_ascii=False))
        return 1
    path = Path(sys.argv[1])
    if not path.exists():
        print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False))
        return 1
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    result, _ = engine(str(path))
    items = []
    if result:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            items.append({
                "text": str(text), "score": float(score),
                "x": min(xs), "y": min(ys),
                "w": max(xs) - min(xs), "h": max(ys) - min(ys),
            })
    # 按行分组（阅读顺序）
    items.sort(key=lambda a: (a["y"], a["x"]))
    lines = []
    for it in items:
        placed = False
        for ln in lines:
            cy = ln["y"] + ln["h"] / 2
            if it["y"] <= cy + 2 and it["y"] + it["h"] >= cy - 2:
                ln["items"].append(it)
                ln["y"] = min(ln["y"], it["y"])
                ln["h"] = max(ln["h"], it["h"])
                placed = True
                break
        if not placed:
            lines.append({"y": it["y"], "h": it["h"], "items": [it]})
    for ln in lines:
        ln["items"].sort(key=lambda a: a["x"])
    # 重叠检测
    overlaps = []
    for ln in lines:
        its = ln["items"]
        for i in range(len(its) - 1):
            a, b = its[i], its[i + 1]
            ov = a["x"] + a["w"] - b["x"]
            if ov > 2:
                overlaps.append({"a": a["text"], "b": b["text"], "overlap_px": int(ov)})
    out = {
        "lines": [" ".join(it["text"] for it in ln["items"]) for ln in lines],
        "items": items,
        "overlaps": overlaps,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
