# recipe：链路保存与复用

[English](recipes.md) | [简体中文](recipes.zh-CN.md)

**每次跑通一条链路，都应该存下来。** 不要让下一次复现从零开始 ——
登录、选服、进某个界面这些"热身步骤"每次都要重来一遍，纯属浪费。

---

## 保存

`session` 日志自动记录**每一次 `send`**（action + args + 是否成功）。

```bash
python tools/bridge.py session clear          # 开始新复现前清一次
python tools/bridge.py send play
python tools/bridge.py send login --arg account=test01 --arg password=xxx
python tools/bridge.py send select_server --arg serverId=1001
python tools/bridge.py send enter_battle --arg battleId=100001

python tools/bridge.py recipe save my-flow    # 只保留 ok=true 的步骤
```

生成的 `tools/recipes/my-flow.json`：

```json
{
  "name": "my-flow",
  "description": "由 session 日志生成（4 步）",
  "steps": [
    { "action": "play" },
    { "action": "login", "args": { "account": "test01", "password": "xxx" } },
    { "action": "select_server", "args": { "serverId": 1001 } },
    { "action": "enter_battle", "args": { "battleId": 100001 } }
  ]
}
```

> ⚠️ 自动生成的是**最小可用版本**，只保证"步骤和参数对"。
> 建议手工补 `wait` / `expect` / 变量替换 —— 见下面两节。

---

## 回放

```bash
# 整条
python tools/bridge.py recipe run my-flow

# 只跑后半段（复用部分环节）
python tools/bridge.py recipe run my-flow --from 3

# 只跑某一步
python tools/bridge.py recipe run my-flow --only 2

# 失败也继续（一次跑完看全貌）
python tools/bridge.py recipe run my-flow --keep-going
```

`--from` 是"只复用部分环节"的关键：比如链路前两步是登录（一天做一次就够），
后面才是真正要反复试的战斗，那平时就 `--from 3` 直接跳到战斗。

---

## 变量替换

**不要把账号密码写死在 recipe 里。** 用 `${VAR}`：

```json
{
  "name": "my-flow",
  "vars": { "ACCOUNT": "test01" },
  "steps": [
    { "action": "login", "args": { "account": "${ACCOUNT}", "password": "${PASSWORD}" } }
  ]
}
```

取值优先级：`--var` > recipe 的 `vars` > 环境变量。

```bash
python tools/bridge.py recipe run my-flow --var ACCOUNT=test02
PASSWORD=xxx python tools/bridge.py recipe run my-flow
```

> 如果整个值就是一个 `${VAR}`，会保留原始类型（数字仍是数字）；
> 嵌在字符串中间（如 `"user_${ID}"`）则按字符串拼接。

---

## 条件等待

很多步骤之后需要等状态变化。用 `expect`：**先触发，再轮询直到条件满足**。

```json
{
  "action": "play",
  "expect": {
    "action": "editor_info",
    "args": {},
    "path": "state.isPlaying",
    "equals": true,
    "timeout": 30
  }
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `action` | **用来轮询的 action，必须是只读的**（反复调用不能有副作用） |
| `args` | 轮询时传的参数 |
| `path` | 结果里的路径，如 `state.curState`、`state.scenes.0` |
| `equals` | 期望值（按字符串比较） |
| `timeout` | 超时秒数，默认 60 |

简单的固定等待用 `wait`（秒）：

```json
{ "action": "select_server", "args": { "serverId": 1001 }, "wait": 5 }
```

`label` 可以给步骤起个人看得懂的名字，回放时打印出来：

```json
{ "action": "enter_battle", "args": { "battleId": 100001 }, "label": "进入战斗 100001" }
```

---

## 一个完整例子

```json
{
  "name": "enter-battle",
  "description": "登录 → 选服 → 主城 → 进入指定战斗（固定种子保证可复现）",
  "vars": { "ACCOUNT": "test01", "SERVER": 1001 },
  "steps": [
    {
      "action": "play",
      "label": "进入播放模式",
      "expect": { "action": "editor_info", "path": "state.isPlaying", "equals": true, "timeout": 60 }
    },
    {
      "action": "login",
      "args": { "account": "${ACCOUNT}", "password": "${PASSWORD}" },
      "label": "登录"
    },
    {
      "action": "select_server",
      "args": { "serverId": "${SERVER}" },
      "label": "选服进主城",
      "expect": { "action": "game_state", "path": "state.curState", "equals": "CITY", "timeout": 90 }
    },
    {
      "action": "enter_battle",
      "args": { "battleId": 100001, "seed": 12345 },
      "label": "进入战斗（种子 12345）",
      "expect": { "action": "game_state", "path": "state.curState", "equals": "BATTLE", "timeout": 60 }
    }
  ]
}
```

---

## ⚠️ recipe 是私有资产

recipe 里通常包含**账号、密码、服务器 ID、内部业务流程**。
**不要提交到公开仓库。**

上游仓库的 `.gitignore` 已经默认忽略 `tools/recipes/*.json`。
也可以直接把 recipe 放在仓库外：

```bash
python tools/bridge.py --recipe-dir /path/to/private-recipes recipe run my-flow
```
