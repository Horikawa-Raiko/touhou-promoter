"""宣发姬云端同步 API — 增量同步 + 提交审核"""
import json, os
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
BASE = "/var/www/touhou-updates"
PENDING_FILE = os.path.join(BASE, "pending.json")
CHANGELOG_FILE = os.path.join(BASE, "changelog.json")


def _load_config():
    """从配置文件读取鉴权信息，不存在则用内置默认值"""
    config_path = "/etc/touhou-api/config.json"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("submit_secret", "raiko-touhou-2026"), cfg.get("admin_key", "raiko-admin-2026")
    # fallback: 开发环境 / 未部署配置文件时使用默认值
    return os.environ.get("TOUHOU_SUBMIT_SECRET", "raiko-touhou-2026"), os.environ.get("TOUHOU_ADMIN_KEY", "raiko-admin-2026")


SECRET, ADMIN_KEY = _load_config()


def load_json(path, default=None):
    if default is None:
        default = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _next_seq():
    changelog = load_json(CHANGELOG_FILE)
    if changelog:
        return changelog[-1]["seq"] + 1
    return 1


# ── 增量同步 ──

@app.route("/api/changes")
def changes():
    since = request.args.get("since", "0")
    try:
        since = int(since)
    except ValueError:
        since = 0

    changelog = load_json(CHANGELOG_FILE)
    if since >= len(changelog):
        return jsonify({"latest_seq": len(changelog), "changes": []})

    new_entries = changelog[since:]  # seq 从1开始，索引从0开始
    return jsonify({
        "latest_seq": len(changelog),
        "changes": new_entries,
    })


# ── 用户提交 ──

@app.route("/api/submit", methods=["POST"])
def submit():
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"ok": False, "error": "empty body"}), 400
    if body.get("secret") != SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 403

    entry = body.get("entry", {})
    required = ["群号", "群名称"]
    for k in required:
        if not entry.get(k):
            return jsonify({"ok": False, "error": f"missing field: {k}"}), 400

    pending = load_json(PENDING_FILE)
    entry["submitted_at"] = datetime.now().isoformat()
    for i, p in enumerate(pending):
        if p.get("群号") == entry["群号"]:
            pending[i] = entry
            save_json(PENDING_FILE, pending)
            return jsonify({"ok": True, "action": "updated", "id": i})

    pending.append(entry)
    save_json(PENDING_FILE, pending)
    return jsonify({"ok": True, "action": "added", "id": len(pending) - 1})


# ── 管理员 ──

@app.route("/api/pending", methods=["GET"])
def list_pending():
    if request.args.get("key") != ADMIN_KEY:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return jsonify(load_json(PENDING_FILE))


@app.route("/api/approve", methods=["POST"])
def approve():
    """批准一条 pending → 追加到 changelog"""
    if request.args.get("key") != ADMIN_KEY:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    body = request.get_json(force=True, silent=True) or {}
    idx = body.get("id")
    if idx is None:
        return jsonify({"ok": False, "error": "missing id"}), 400

    pending = load_json(PENDING_FILE)
    if idx < 0 or idx >= len(pending):
        return jsonify({"ok": False, "error": "bad id"}), 400

    entry = pending.pop(idx)
    save_json(PENDING_FILE, pending)

    new_entry = {
        "seq": _next_seq(),
        "群号": entry["群号"],
        "群名称": entry["群名称"],
        "大类": entry.get("大类", ""),
        "地区/小类": entry.get("地区/小类", ""),
        "子类": entry.get("子类", ""),
        "地点": entry.get("地点", ""),
        "学校": entry.get("学校", ""),
        "活动名": entry.get("活动名", ""),
        "说明": entry.get("说明", ""),
    }
    changelog = load_json(CHANGELOG_FILE)
    changelog.append(new_entry)
    save_json(CHANGELOG_FILE, changelog)

    # 同步更新完整 CSV（兼容旧客户端）
    _rebuild_csv(changelog)

    return jsonify({"ok": True, "seq": new_entry["seq"]})


def _rebuild_csv(changelog):
    import csv
    fields = ["大类", "地区/小类", "子类", "地点", "学校", "活动名", "群号", "群名称", "说明"]
    csv_path = os.path.join(BASE, "东方QQ群列表.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for e in changelog:
            writer.writerow({k: e.get(k, "") for k in fields})

    # 更新 version 供客户端检查更新
    with open(os.path.join(BASE, "version.json"), "w", encoding="utf-8") as f:
        json.dump({
            "app_version": "1.0.0",
            "latest_seq": len(changelog),
            "csv_version": len(changelog),
            "download_url": "https://s3.bitiful.net/raiko/download/%E4%B8%9C%E6%96%B9Project%E4%B8%80%E9%94%AE%E5%AE%A3%E5%8F%91%E5%A7%AC.exe",
            "updater_url": "https://s3.bitiful.net/raiko/updater/updater.exe",
            "sha256": "3c0b3fd7486e75ee94949f2731952b5df4a7034c97acd2efb4fe55507c75107f",
        }, f, ensure_ascii=False)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8800)
