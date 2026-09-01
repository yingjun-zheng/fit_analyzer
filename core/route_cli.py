"""路书分析命令行入口。

用法：
  python -m core.route_cli import <gpx文件>                # 导入并打印路书摘要
  python -m core.route_cli import <gpx文件> --out 输出.gpx  # 导入并导出路书
"""
import argparse
import sys

from . import route


def main(argv=None):
    p = argparse.ArgumentParser(prog="route", description="骑行路书分析（GPX 导入/爬坡分级/导出）")
    sub = p.add_subparsers(dest="cmd")

    imp = sub.add_parser("import", help="导入 GPX 并分析")
    imp.add_argument("gpx", help="GPX 文件路径")
    imp.add_argument("--enrich", action="store_true", help="缺海拔时联网（Open-Meteo）补全海拔")
    imp.add_argument("--out", help="导出路书到指定 .gpx 路径（可选）")
    imp.set_defaults(func=cmd_import)

    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_help()
        return 1
    return args.func(args)


def cmd_import(args):
    r = route.parse_gpx(args.gpx, enrich_elevation=args.enrich)
    print(route.summarize(r))
    print()

    if args.out:
        out = route.export_route_gpx(r, args.out)
        print(f"✅ 路书已导出：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
