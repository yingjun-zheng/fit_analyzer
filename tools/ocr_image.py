"""图片 OCR 识别工具：把截图变成文字，并检测文本重叠（用于分析图表坐标标签等问题）。

用法:
    python tools/ocr_image.py <图片路径> [更多图片...]

功能:
    1. OCR 识别图片中的文字（中文/英文/数字），按阅读顺序输出
    2. 检测疑似重叠的文本块（同一行内水平重叠）——可用来排查图表坐标标签重叠
    3. 结果同时保存为 <图片名>.ocr.txt

依赖（一次性安装）:
    pip install rapidocr_onnxruntime
"""
import argparse
import json
import sys
from pathlib import Path


def ocr_items(path: Path):
    """OCR 识别，返回 [{x,y,w,h,text,score}]，按阅读顺序（先按行、行内按 x）。"""
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    result, _ = engine(str(path))
    items = []
    if result:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            items.append({
                "x": min(xs), "y": min(ys),
                "w": max(xs) - min(xs), "h": max(ys) - min(ys),
                "text": str(text), "score": float(score),
            })
    # 按行分组：y 中心接近的归为一行，行内按 x 排序
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
    return items, lines


def detect_overlaps(lines, tol=2):
    """检测同一行内文本块的水平重叠。返回 [(textA, textB, 重叠像素)]。"""
    issues = []
    for ln in lines:
        its = ln["items"]
        for i in range(len(its) - 1):
            a, b = its[i], its[i + 1]
            overlap = a["x"] + a["w"] - b["x"]
            if overlap > tol:
                issues.append((a["text"], b["text"], int(overlap)))
    return issues


def main():
    ap = argparse.ArgumentParser(description="图片 OCR + 文本重叠检测")
    ap.add_argument("images", nargs="+", help="图片路径")
    ap.add_argument("--json", action="store_true", help="同时输出 JSON 结果")
    args = ap.parse_args()

    for img in args.images:
        p = Path(img)
        if not p.exists():
            print(f"!! 文件不存在: {p}")
            continue
        print(f"\n{'=' * 60}\n图片: {p}\n{'=' * 60}")
        try:
            items, lines = ocr_items(p)
        except Exception as e:
            print(f"OCR 失败: {e}")
            continue
        if not items:
            print("（未识别到文字）")
            continue

        print("\n--- 识别文本（按阅读顺序）---")
        for ln in lines:
            print("  " + " ".join(it["text"] for it in ln["items"]))

        issues = detect_overlaps(lines)
        print("\n--- 重叠检测 ---")
        if issues:
            print(f"!! 发现 {len(issues)} 处疑似重叠：")
            for a, b, ov in issues[:10]:
                print(f"   「{a}」 与 「{b}」 重叠约 {ov}px")
        else:
            print("  未发现重叠文本")

        # 保存结果（图片目录不可写时回退到当前目录）
        out = p.with_name(p.stem + ".ocr.txt")
        try:
            out.write_text("", encoding="utf-8")
        except OSError:
            out = Path.cwd() / (p.stem + ".ocr.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# OCR: {p}\n")
            for ln in lines:
                f.write(" ".join(it["text"] for it in ln["items"]) + "\n")
            if issues:
                f.write("\n# 疑似重叠:\n")
                for a, b, ov in issues:
                    f.write(f"{a} | {b} | {ov}px\n")
        print(f"\n结果已保存: {out}")
        if args.json:
            jout = p.with_name(p.stem + ".ocr.json")
            try:
                jout.write_text(json.dumps({"items": items, "lines": [
                    [it["text"] for it in ln["items"]] for ln in lines]},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"JSON 已保存: {jout}")
            except OSError:
                jout = Path.cwd() / (p.stem + ".ocr.json")
                jout.write_text(json.dumps({"items": items, "lines": [
                    [it["text"] for it in ln["items"]] for ln in lines]},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"JSON 已保存: {jout}")


if __name__ == "__main__":
    sys.exit(main())
