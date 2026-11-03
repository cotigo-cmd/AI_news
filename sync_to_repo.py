# -*- coding: utf-8 -*-
"""把发布产物 AI_News_site/ 同步到 GitHub 仓库，并提交、推送、校验。

用法：
  python sync_to_repo.py                # 复制 + 提交 + 推送 + 校验
  python sync_to_repo.py --no-push      # 复制 + 提交，不推送
  python sync_to_repo.py --dry-run      # 只复制，不动 git

退出码 0 = 已确认远程 HEAD 与本地产物一致；非 0 = 失败（不会静默跳过）。
"""
import os
import re
import sys
import datetime
import shutil
import subprocess

WS = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(os.path.dirname(WS), "AI_News_site")
REPO = r"D:/source/git-project/AI_news"
BRANCH = "main"
NOW = datetime.datetime.now()


def cp(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def git(*args, check=True):
    r = subprocess.run(("git",) + args, cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit("git %s 失败：\n%s\n%s" % (" ".join(args), r.stdout, r.stderr))
    return (r.stdout or "").strip()


def copy_all():
    # 实时版 -> repo/live.html
    cp(os.path.join(SITE, "live.html"), os.path.join(REPO, "live.html"))
    # 归档索引页 -> repo/index.html
    cp(os.path.join(SITE, "index.html"), os.path.join(REPO, "index.html"))
    # 归档页
    for kind in ("daily", "weekly"):
        sdir = os.path.join(SITE, "archive", kind)
        ddir = os.path.join(REPO, "archive", kind)
        os.makedirs(ddir, exist_ok=True)
        if not os.path.isdir(sdir):
            continue
        for f in sorted(os.listdir(sdir)):
            if f.endswith(".html"):
                cp(os.path.join(sdir, f), os.path.join(ddir, f))
    # 生成脚本与模板
    for f in ("gen_briefing.py", "live_template.html", "archive_index_template.html",
              "build_site.py", "sync_to_repo.py"):
        src = os.path.join(WS, f)
        if os.path.exists(src):
            cp(src, os.path.join(REPO, f))
    print("[copy] 产物已复制到", REPO)


def commit_and_push(do_push=True):
    git("add", "-A")
    if git("status", "--porcelain"):
        msg = "chore: 发布 %s 期内容（%s）" % (NOW.strftime("%Y-%m-%d"), NOW.strftime("%H:%M"))
        git("commit", "-q", "-m", msg)
        print("[commit]", msg)
    else:
        print("[commit] 无变更，跳过")

    if not do_push:
        print("[push] 已跳过（--no-push）")
        return
    git("push", "origin", BRANCH)
    print("[push] 已推送到 origin/" + BRANCH)


def verify():
    """校验：工作区已清空、远程 HEAD 与本地一致、远程 live.html 快照是今天。"""
    dirty = git("status", "--porcelain")
    if dirty:
        raise SystemExit("[verify] 失败：仍有未提交改动，内容没进仓库：\n" + dirty[:500])

    local = git("rev-parse", "HEAD")
    git("fetch", "origin", BRANCH, check=False)
    remote = git("rev-parse", "origin/" + BRANCH)
    if local != remote:
        raise SystemExit("[verify] 失败：本地 %s ≠ 远程 %s" % (local[:7], remote[:7]))

    html = git("show", "origin/%s:live.html" % BRANCH, check=False)
    m = re.search(r'"ts":"([^"]*)"', html)
    ts = m.group(1) if m else ""
    today = NOW.strftime("%Y 年 %m 月 %d 日")
    if today not in ts:
        raise SystemExit("[verify] 失败：远程 live.html 数据时间为 %r，不是今天（%s）" % (ts, today))
    print("[verify] PASS · 远程 HEAD %s · 数据时间 %s" % (remote[:7], ts))


def main():
    dry = "--dry-run" in sys.argv
    push = "--no-push" not in sys.argv
    copy_all()
    if dry:
        print("[dry-run] 未执行 git 操作")
        return
    commit_and_push(push)
    if push:
        verify()


if __name__ == "__main__":
    main()
