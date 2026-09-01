"""复盘 Agent 端到端验证脚本（真实 LLM）。

用法：
  python tests/e2e_review.py --base-url <中转站/v1> --api-key <key> [--model <模型名>]

会依次跑 4 种复盘意图，打印真实 LLM 输出。默认模型 deepseek-chat。

示例：
  python tests/e2e_review.py --base-url https://xxx.com/v1 --api-key sk-xxx
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import fit_parser, logging_setup
from core.config import Config
from core import db as db_mod
from core.ai_client import AIClient
from core import review_agent


def _find_fit_dir():
    for cand in (Path(r"F:\byciclefits"), Path(r"C:\Users\zhengyingjun\Documents\deepseek\fittestdata")):
        if cand.exists() and any(cand.glob("*.fit")):
            return cand
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--question", default=None, help="只跑一个问题（省略则跑默认 4 条）")
    args = ap.parse_args()

    fit_dir = _find_fit_dir()
    if fit_dir is None:
        print("!! 未找到 FIT 数据")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="e2e_review_"))
    logging_setup.setup_logging(tmp, console=False)
    cfg = Config(tmp / "config.json")
    db = db_mod.DB(tmp / "fit.db")
    rs, es = fit_parser.parse_many(sorted(fit_dir.glob("*.fit")))
    for r in rs:
        db.upsert_activity(r["data"])
    print(f"已导入 {len(rs)} 条活动\n")

    ai = AIClient(base_url=args.base_url, api_key=args.api_key,
                  model=args.model, temperature=0.4, timeout=120)

    questions = [args.question] if args.question else [
        "帮我复盘上周的骑行",
        "和上次比有没有进步",
        "这周该不该休息",
        "我体能进步了吗",
    ]

    for q in questions:
        print("=" * 60)
        print(f"问：{q}")
        print("-" * 60)
        try:
            r = review_agent.run_review(ai, db, cfg, q)
            intent_cn = {"single": "单次", "period": "周期", "compare": "对比",
                         "load": "训练负荷", "fitness": "体能"}.get(r.get("intent"), r.get("intent"))
            print(f"[类型] {intent_cn}")
            print(r.get("answer") or "（无结果）")
        except Exception as e:
            print(f"❌ 失败：{e}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
