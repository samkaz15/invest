#!/usr/bin/env python3
"""Render sourced political snapshots, without forecasting or intraday data."""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

KINDS = {"official", "official_preliminary", "official_certified", "poll", "media_projection", "policy", "calendar", "daily_market", "context"}
TOPICS = {"history", "situation", "issues", "policy_conditions", "market", "economic_path", "upcoming", "election", "missing"}

def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.utcoffset() is None:
            raise ValueError()
        return dt
    except (ValueError, AttributeError):
        raise ValueError("日時はタイムゾーン付き ISO 8601 が必要です") from None

def validate(doc, as_of=None):
    if not isinstance(doc, dict) or not all(isinstance(doc.get(k), str) and doc[k].strip() for k in ("country", "event", "observed_at")):
        raise ValueError("country, event, observed_at は必須です")
    observed = timestamp(doc["observed_at"])
    if as_of and observed.date() > as_of:
        raise ValueError("観測日時が as-of より後です")
    if not isinstance(doc.get("records"), list):
        raise ValueError("records は配列が必要です")
    for i, row in enumerate(doc["records"]):
        if not isinstance(row, dict) or row.get("label") not in {"FACT", "REPORTED", "INFERENCE"} or row.get("topic") not in TOPICS or row.get("kind") not in KINDS or not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError(f"records[{i}] の label / topic / kind / text が不正です")
        if "published_at" not in row:
            raise ValueError(f"records[{i}] の published_at がありません。未確認は null")
        if row["published_at"] is not None and timestamp(row["published_at"]) > observed:
            raise ValueError(f"records[{i}] は観測後に公表された情報です")
        url = row.get("source_url")
        if not isinstance(url, str) or urlparse(url).scheme != "https" or not urlparse(url).netloc:
            raise ValueError(f"records[{i}] は HTTPS 出典 URL が必要です")
        if row["label"] == "INFERENCE" and not row.get("basis"):
            raise ValueError(f"records[{i}] は推論根拠が必要です")
        if row["kind"] == "daily_market":
            if row.get("frequency") not in ("daily", "weekly", "monthly") or not all(row.get(k) is not None for k in ("market_date", "instrument", "unit", "value")):
                raise ValueError(f"records[{i}] 市場値は日次以上と日付・銘柄・値・単位が必要です")
            if date.fromisoformat(row["market_date"]) > observed.date():
                raise ValueError(f"records[{i}] 市場観測日が将来です")
        if row.get("election") is not None:
            e = row["election"]
            if row["topic"] != "election" or row["label"] != "FACT" or row["kind"] not in {"official", "official_preliminary", "official_certified"} or not isinstance(e, dict):
                raise ValueError(f"records[{i}] 議席計算には公式選挙情報が必要です")
            total, won = e.get("total_seats"), e.get("party_seats")
            majority(total)
            if isinstance(won, bool) or not isinstance(won, int) or won < 0 or won > total:
                raise ValueError(f"records[{i}] の党派議席数が不正です")
            if e.get("threshold_rule") != "absolute_total_seats":
                raise ValueError("議席差の計算には総定数の絶対過半数を明示してください")
    return doc

def majority(seats):
    if isinstance(seats, bool) or not isinstance(seats, int) or seats <= 0:
        raise ValueError("議席数は正の整数が必要です")
    return seats // 2 + 1

def render(doc, as_of, previous=None):
    validate(doc, as_of)
    if previous is not None:
        validate(previous, as_of)
        if previous["country"] != doc["country"] or previous["event"] != doc["event"] or timestamp(previous["observed_at"]) >= timestamp(doc["observed_at"]):
            raise ValueError("比較対象は同一国・同一イベントの過去記録に限ります")
    out = [f"# {doc['country']}：{doc['event']}", "", f"分析対象日時：{doc['observed_at']} / as-of：{as_of.isoformat()}", ""]
    if doc.get("supersedes"):
        out += [f"補完・訂正元：{doc['supersedes']}", ""]
    sections = [("history","歴史的背景"),("situation","現在の政治経済情勢"),("election","選挙・議席"),("issues","主要争点"),("policy_conditions","政策の実現条件"),("market","確認された市場反応"),("economic_path","経済的な影響経路"),("upcoming","今後の公式イベント"),("missing","未確認事項")]
    for key, title in sections:
        out += [f"## {title}", ""]
        rows = [x for x in doc["records"] if x["topic"] == key]
        if not rows:
            out += ["未確認。", ""]
        for x in rows:
            published = x["published_at"] or "公表日時不明"
            basis = f" 根拠：{x['basis']}" if x.get("basis") else ""
            out += [f"- [{x['label']}/{x['kind']}] {x['text']}（公表：{published}、[出典]({x['source_url']})）{basis}", ""]
            if x.get("election"):
                e = x["election"]
                out += [f"  総定数の絶対過半数：{majority(e['total_seats'])}議席。対象党派の不足：{max(0, majority(e['total_seats']) - e['party_seats'])}議席。別の採決要件は未評価。", ""]
    out += ["## 前回との差分", ""]
    if previous is None:
        out += ["比較可能な前回記録なし。", ""]
    else:
        old = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in previous["records"]}
        new = [x for x in doc["records"] if json.dumps(x, sort_keys=True, ensure_ascii=False) not in old]
        out += ([f"- [{x['label']}] {x['text']}" for x in new] if new else ["同一内容の追加なし。取得状況の不足は未確認事項を参照。"])
        out += [""]
    out += ["※未検証の価格・選挙予測や売買指示は含まない。", ""]
    return "\n".join(out)

def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    v = subs.add_parser("validate"); v.add_argument("snapshot")
    r = subs.add_parser("report"); r.add_argument("snapshot"); r.add_argument("output"); r.add_argument("--as-of", required=True); r.add_argument("--previous")
    args = parser.parse_args()
    try:
        doc = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        if args.action == "validate":
            validate(doc); print("OK"); return 0
        prev = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
        result = render(doc, date.fromisoformat(args.as_of), prev)
        with Path(args.output).open("x", encoding="utf-8") as f:
            f.write(result)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 1

if __name__ == "__main__":
    raise SystemExit(main())
