# 上游仓库的脱敏原则

这个仓库开源的是**能力本身**，不是任何具体项目的业务。
每次提交前对照本清单过一遍。

---

## 该留在上游的

- 桥的骨架（`AgentBridge.cs`）：轮询、分发、自动抢焦点
- **通用** action（`BridgeActions.cs`）：`ping` / `play` / `stop` / `frame` / `open_scene` / `probe` …
- 驱动 CLI（`bridge.py`）与 recipe 机制
- 文档：架构、加 action 的规则、坑

判断标准：**换个 Unity 工程还能原样用吗？** 能 → 上游；不能 → 项目侧。

---

## 不该出现在上游的

| 类别 | 例子 |
|---|---|
| 项目专有 action | `login` / `select_server` / `send_world_chat` / `game_state` |
| 业务标识 | 游戏名、包名、服务器 ID、区服名、内部代号 |
| 凭据 | 账号、密码、token、API key |
| 内网信息 | IP、端口、域名、机器别名 |
| 业务流程 | 具体玩法名、协议名、配置表名 |
| recipe / session | 里面必然带上面这些 |

---

## 提交前自检

```bash
# 1. 确认没有项目专属 action 混进通用文件
grep -n "BridgeAction" unity/Assets/Editor/AgentBridge/BridgeActions.cs

# 2. 全文搜项目专有标识（按你的项目替换关键词）
grep -rniE "你的游戏名|你的包名|你的用户名" . --exclude-dir=.git

# 3. 搜内网地址与凭据
grep -rniE "([0-9]{1,3}\.){3}[0-9]{1,3}|password|passwd|secret|token|api[_-]?key" . \
  --exclude-dir=.git --exclude=open-sourcing.md

# 4. 确认 recipe 目录只有示例
ls tools/recipes/

# 5. 看看到底会提交哪些文件
git status --short
git diff --cached --stat
```

第 3 条会命中文档里的示例文字，人工判断即可 —— **重点是别漏掉真实凭据**。

---

## 怎么把项目内容挡在仓库外

上游仓库的 `.gitignore` 已默认忽略 `tools/recipes/*.json`。
项目侧建议：

```
你的Unity工程/
└── Assets/Editor/AgentBridge/
    ├── AgentBridge.cs            # 从上游同步
    ├── BridgeActions.cs          # 从上游同步
    └── ProjectBridgeActions.cs   # 你的项目专属 action，只留在私有仓库
```

只需要 `namespace AgentBridge` + `[BridgeAction]` 就会被发现，**不需要注册**，
所以通用文件和项目文件可以物理分开、各自独立升级。

recipe 同理 —— 放到仓库外用 `--recipe-dir` 指过去：

```bash
python tools/bridge.py --recipe-dir /path/to/private-recipes recipe run my-flow
```

---

## 第一次开源时

1. 建库 → 只放通用能力 → 推
2. **事后用 GitHub 的搜索再验一遍**：搜项目名、搜内网 IP 段
3. 历史里如果误提交过凭据：**光删文件没用**（`git log` 里还在），
   必须改写历史或直接废弃仓库重建
