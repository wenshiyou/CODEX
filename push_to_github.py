# -*- coding: utf-8 -*-
"""通过GitHub API推送所有git跟踪的文本文件（排除图片/exe/大模型）到远程仓库"""
import urllib.request, urllib.error, json, base64, subprocess, os, sys

# 从git remote URL解析token和仓库信息
remote = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], text=True).strip()
# URL格式: https://username:token@github.com/owner/repo.git
import re
m = re.match(r"https://([^:]+):([^@]+)@github\.com/([^/]+)/(.+)\.git", remote)
if not m:
    print("无法解析远程URL"); sys.exit(1)
username, token, owner, repo = m.group(1), m.group(2), m.group(3), m.group(4)
print(f"仓库: {owner}/{repo}")

api = f"https://api.github.com/repos/{owner}/{repo}"
headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "MapleBot-Push"
}

def api_call(method, path, data=None):
    url = api + path if path.startswith("/") else path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()) if r.read else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  API错误 {e.code}: {err[:200]}")
        return None

# 获取远程main分支最新commit
ref = api_call("GET", "/git/refs/heads/main")
if not ref:
    print("无法获取远程分支信息"); sys.exit(1)
latest_commit_sha = ref["object"]["sha"]
print(f"远程最新commit: {latest_commit_sha[:8]}")

# 获取最新commit的tree
commit = api_call("GET", f"/git/commits/{latest_commit_sha}")
base_tree = commit["tree"]["sha"]

# 获取所有git跟踪的文件
files = subprocess.check_output(["git", "ls-files"], text=True).strip().split("\n")
# 排除图片、exe、onnx、log、tmp、pyc
skip_ext = {".png",".jpg",".jpeg",".gif",".bmp",".ico",".webp",".tif",".tiff",".exe",".onnx",".log",".tmp",".pyc"}
push_files = []
for f in files:
    ext = os.path.splitext(f)[1].lower()
    if ext in skip_ext:
        continue
    if not os.path.isfile(f):
        continue
    push_files.append(f)

print(f"需要推送: {len(push_files)} 个文件")

# 用Git Tree API一次性创建tree
tree_items = []
for f in push_files:
    with open(f, "rb") as fh:
        content = fh.read()
    # 文本文件直接传content，二进制文件用base64
    try:
        text = content.decode("utf-8")
        tree_items.append({"path": f, "mode": "100644", "type": "blob", "content": text})
    except UnicodeDecodeError:
        b64 = base64.b64encode(content).decode()
        tree_items.append({"path": f, "mode": "100644", "type": "blob", "content": b64, "encoding": "base64"})

print("创建tree...")
new_tree = api_call("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_items})
if not new_tree:
    print("创建tree失败"); sys.exit(1)
print(f"新tree: {new_tree['sha'][:8]}")

# 创建commit
print("创建commit...")
new_commit = api_call("POST", "/git/commits", {
    "message": "倍率和录制完整版",
    "tree": new_tree["sha"],
    "parents": [latest_commit_sha]
})
if not new_commit:
    print("创建commit失败"); sys.exit(1)
print(f"新commit: {new_commit['sha'][:8]}")

# 更新分支引用
print("更新main分支...")
result = api_call("PATCH", "/git/refs/heads/main", {"sha": new_commit["sha"], "force": False})
if result:
    print(f"推送成功! 远程main已更新到 {new_commit['sha'][:8]}")
else:
    print("更新分支引用失败")
