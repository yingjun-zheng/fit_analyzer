"""骑行复盘 Agent 命令行入口。

用法：
  python -m core.review_cli "帮我复盘上周的骑行"
  python -m core.review_cli "和上次比有没有进步"
  python -m core.review_cli "这周该不该休息"

一句话触发，内部路由到单次/周期/对比/训练负荷四种复盘。
复用 fit_analyzer 的数据目录（%APPDATA%/FitAnalyzer）与 AI 配置。
"""
import argparse
import logging
import os
import sys
from pathlib import Path


def default_data_dir():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "FitAnalyzer"


def main():
    parser = argparse.ArgumentParser(description="骑行复盘 Agent（对话式）")
    parser.add_argument("question", nargs="?", default=None, help="复盘问题；省略则进入交互式对话")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认 %APPDATA%/FitAnalyzer）")
    parser.add_argument("--debug", action="store_true", help="详细日志")
    args = parser.parse_args()

    from core import logging_setup
    from core.config import Config
    from core import db as db_mod
    from core.ai_client import AIClient

    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    logger = logging_setup.setup_logging(data_dir, level=logging.DEBUG if args.debug else logging.INFO)
    logger.info("骑行复盘 Agent 启动，数据目录 %s", data_dir)

    config = Config(data_dir / "config.json")
    db = db_mod.DB(data_dir / "fit.db")

    if db.count() == 0:
        print("⚠️ 数据库中还没有骑行记录。请先用「骑行FIT数据分析器」导入 FIT 文件。")
        return 1

    if not config.get("ai_enabled"):
        print("⚠️ 未启用 AI。请在「骑行FIT数据分析器 → 设置 → AI」里配置模型后重试。")
        return 1

    ai = AIClient(
        base_url=config.get("ai_base_url"),
        api_key=config.get("ai_api_key"),
        model=config.get("ai_model"),
        temperature=config.get("ai_temperature", 0.4),
        timeout=config.get("ai_timeout", 120),
    )

    from core.review_agent import run_review

    def once(q):
        print(f"\n🧭 复盘：{q}\n")
        try:
            result = run_review(ai, db, config, q)
        except Exception as e:  # noqa: BLE001
            print(f"❌ 复盘失败：{e}")
            return
        print(result.get("answer") or "（无结果）")
        print()

    if args.question:
        once(args.question)
        return 0

    # 交互模式
    print("=== 骑行复盘 Agent（输入问题，exit 退出）===")
    while True:
        try:
            q = input("\n你 › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 已退出。")
            break
        if not q:
            continue
        if q.lower() in ("exit", "quit", "q"):
            print("👋 已退出。")
            break
        once(q)
    return 0


if __name__ == "__main__":
    sys.exit(main())
