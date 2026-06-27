#!/usr/bin/env python3
"""
飞书群每日 QA 客观执行差异播报 (GitHub Actions 版)
数据来源: 培训部数据看板 GitHub (d2112ds12d12d/Qgkb)
"""

import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

import requests

DATA_REPO = "d2112ds12d12d/Qgkb"
DATA_BRANCH = "main"
DATA_FOLDER = "QGZLdata"
RAW_BASE = f"https://raw.githubusercontent.com/{DATA_REPO}/{DATA_BRANCH}/{DATA_FOLDER}"

MY_SITE = "重庆库"


def fetch_json(filename):
    url = f"{RAW_BASE}/{filename}"
    print(f"[INFO] 获取: {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_yesterday_data(rows, site, yesterday):
    """从 qa_diff 中提取指定站点、指定日期的数据"""
    site_rows = [r for r in rows if r.get("site") == site and r.get("date") == yesterday]
    if not site_rows:
        return None

    total_checks = sum(r.get("checks", 0) for r in site_rows)
    total_diff = sum(r.get("objDiff", 0) for r in site_rows)
    rate = f"{total_diff / total_checks * 100:.1f}%" if total_checks > 0 else "0%"

    return {
        "date": yesterday,
        "site": site,
        "checks": total_checks,
        "objDiff": total_diff,
        "rate": rate,
    }


def get_prev_period_avg(rows, site, yesterday, days=7):
    """获取前 N 天均值作对比基线"""
    daily = defaultdict(lambda: {"checks": 0, "objDiff": 0})
    for r in rows:
        if r.get("site") == site and r.get("date", "") < yesterday:
            d = r.get("date", "")
            daily[d]["checks"] += r.get("checks", 0)
            daily[d]["objDiff"] += r.get("objDiff", 0)

    recent = sorted(daily.items())[-days:]
    if not recent:
        return None, 0

    avg_checks = sum(d[1]["checks"] for d in recent) / len(recent)
    avg_diff = sum(d[1]["objDiff"] for d in recent) / len(recent)
    avg_rate = avg_diff / avg_checks * 100 if avg_checks > 0 else 0

    return avg_diff, avg_rate


def build_card(data, prev_avg, prev_rate):
    date_str = data["date"]
    diff = data["objDiff"]
    rate = data["rate"]
    checks = data["checks"]

    if prev_avg is not None:
        diff_change = diff - prev_avg
        arrow = "↑" if diff_change > 0 else ("↓" if diff_change < 0 else "→")
        trend = f"{arrow} {abs(diff_change):.1f} 条（近7日均值 {prev_avg:.1f}）"
    else:
        trend = "暂无基线"

    card_md = (
        f"**📍 站点：{data['site']}**\n\n"
        f"📦 抽检量：**{checks}** 台\n"
        f"⚠️ 客观差异：**{diff}** 条\n"
        f"📊 差异率：**{rate}**\n"
        f"📈 趋势对比：{trend}"
    )

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"📱 昨日QA客观执行差异 | {date_str}"},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": card_md}},
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"📊 重庆库　|　每日自动播报　|　{datetime.now().strftime('%Y-%m-%d %H:%M')}"}
                    ],
                },
            ],
        },
    }


def send_to_feishu(webhook_url, card):
    print(f"[INFO] 发送到飞书...")
    try:
        resp = requests.post(webhook_url, json=card, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        print(f"[INFO] 响应: {json.dumps(result, ensure_ascii=False)}")
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            print("[OK] 发送成功！")
            return True
        else:
            print(f"[ERROR] 飞书错误: {result}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 请求失败: {e}")
        return False


def main():
    print(f"[INFO] ====== 重庆库 QA 客观执行差异日报 ======")
    print(f"[INFO] 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook_url:
        print("[ERROR] 未设置 FEISHU_WEBHOOK_URL 环境变量")
        sys.exit(1)

    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    ym = now.strftime("%Y-%m")

    qa_rows = fetch_json(f"qa_diff_{ym}.json").get("rows", [])

    data = get_yesterday_data(qa_rows, MY_SITE, yesterday)

    if data is None:
        site_dates = sorted(set(
            r["date"] for r in qa_rows if r.get("site") == MY_SITE
        ))
        if not site_dates:
            print("[WARN] 本月无数据，尝试上月...")
            last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            qa_rows = fetch_json(f"qa_diff_{last_month}.json").get("rows", [])
            site_dates = sorted(set(
                r["date"] for r in qa_rows if r.get("site") == MY_SITE
            ))

        if site_dates:
            latest = site_dates[-1]
            data = get_yesterday_data(qa_rows, MY_SITE, latest)
            if data:
                print(f"[INFO] {yesterday} 无数据，使用最新: {latest}")
        else:
            print("[WARN] 无数据，退出")
            return

    if data is None:
        print("[WARN] 无数据，退出")
        return

    print(f"[INFO] {data['site']} {data['date']}: 抽检 {data['checks']} 差异 {data['objDiff']} 差异率 {data['rate']}")

    prev_avg, prev_rate = get_prev_period_avg(qa_rows, MY_SITE, yesterday)
    card = build_card(data, prev_avg, prev_rate)

    success = send_to_feishu(webhook_url, card)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
