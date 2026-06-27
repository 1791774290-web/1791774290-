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

# ── 数据源配置 ──────────────────────────────────────────────
DATA_REPO = "d2112ds12d12d/Qgkb"
DATA_BRANCH = "main"
DATA_FOLDER = "QGZLdata"
RAW_BASE = f"https://raw.githubusercontent.com/{DATA_REPO}/{DATA_BRANCH}/{DATA_FOLDER}"

# 播报覆盖的分站
MY_SITES = ["重庆库"]


def fetch_json(filename):
    """从 GitHub 获取 JSON 文件"""
    url = f"{RAW_BASE}/{filename}"
    print(f"[INFO] 获取: {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def compute_detailed_stats(rows, sites, target_date=""):
    """从 phone_diff 明细计算 TOP 人员 & 问题项（按日过滤）"""
    filtered = [
        r for r in rows
        if r.get("site") in sites
        and "客观" in r.get("subjobj", "")
        and r.get("judgedType") == "执行问题"
        and (not target_date or r.get("date", "") == target_date)
    ]

    if not filtered:
        return None

    person_diff = defaultdict(int)
    issue_diff = defaultdict(int)
    site_diff = defaultdict(int)

    for r in filtered:
        person = r.get("inspector") or ""
        if not person or person.lower() == "null" or person.strip() == "":
            person = "(未署名)"
        person_diff[person] += 1

        l1 = r.get("level1", "") or ""
        l3 = r.get("level3_new", "") or ""
        label = f"{l1} — {l3}" if l1 and l3 else (l1 or l3 or "未知")
        issue_diff[label] += 1

        site_diff[r.get("site", "")] += 1

    return {
        "total": len(filtered),
        "target_date": target_date,
        "sites": dict(site_diff),
        "top_persons": sorted(person_diff.items(), key=lambda x: -x[1]),
        "top_issues": sorted(issue_diff.items(), key=lambda x: -x[1]),
    }


def build_card(detail, top_n=5):
    """构造飞书交互卡片"""

    site_list = "、".join([f"{k}: {v}条" for k, v in detail["sites"].items()])

    person_lines = []
    for i, (name, count) in enumerate(detail["top_persons"][:top_n], 1):
        medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
        person_lines.append(f"{medal} **{name}**　　{count} 条差异")

    issue_lines = []
    for i, (name, count) in enumerate(detail["top_issues"][:top_n], 1):
        medal = ["🏆", "⚠️", "⚠️"][i - 1] if i <= 3 else "▸"
        issue_lines.append(f"{medal} **{name}**　　{count} 条差异")

    card_md = (
        f"**📅 日期：{detail['target_date']}**\n"
        f"**📍 站点：{site_list}**\n\n---\n\n"
        f"**👤 TOP{top_n} 差异人员**\n"
        + "\n".join(person_lines)
        + f"\n\n---\n\n"
        f"**⚠️ TOP{top_n} 差异问题项**\n"
        + "\n".join(issue_lines)
    )

    target_date = detail["target_date"]
    header_title = f"📱 昨日QA客观执行差异 | {target_date}"

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": header_title},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": card_md}},
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"📊 客观执行差异共 {detail['total']} 条　|　重庆库　|　自动播报"}
                    ],
                },
            ],
        },
    }


def send_to_feishu(webhook_url, card):
    """发送卡片到飞书"""
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
    print(f"[INFO] ====== QA 客观执行差异日报 ======")
    print(f"[INFO] 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if not webhook_url:
        print("[ERROR] 未设置 FEISHU_WEBHOOK_URL 环境变量")
        sys.exit(1)

    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    ym = now.strftime("%Y-%m")

    # 获取明细数据
    detail_rows = fetch_json(f"phone_diff_{ym}.json").get("rows", [])
    print(f"[INFO] 明细行数: {len(detail_rows)}")

    # 只取昨日客观执行问题
    print(f"[INFO] 目标日期: {yesterday}, 站点: {MY_SITES}")
    detail = compute_detailed_stats(detail_rows, MY_SITES, target_date=yesterday)

    if detail is None or detail["total"] == 0:
        print(f"[WARN] {yesterday} 无数据，尝试上月...")
        last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        detail_rows = fetch_json(f"phone_diff_{last_month}.json").get("rows", [])
        detail = compute_detailed_stats(detail_rows, MY_SITES, target_date=yesterday)
        if detail is None or detail["total"] == 0:
            print("[WARN] 无数据，退出")
            return

    print(f"[INFO] 差异: {detail['total']} 条")
    print(f"[INFO] TOP人员: {[p[0] for p in detail['top_persons'][:5]]}")
    print(f"[INFO] TOP问题: {[p[0] for p in detail['top_issues'][:5]]}")

    card = build_card(detail)
    success = send_to_feishu(webhook_url, card)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
