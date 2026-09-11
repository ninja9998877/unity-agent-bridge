# unity-agent-bridge

**让 AI agent 自己把 Unity 游戏开到出问题的那一幕，读完状态再回来改代码。**

[English](README.md) | [简体中文](README.zh-CN.md)

`Unity 2019+` · `AI Agent` · `场景级复现` · `MIT`

---

> **🤖 你是 AI agent？** 直接跳到 [**给 AI agent**](#给-ai-agent) —— 那是你的工作规则，读完再动手。
>
> **👤 你是人？** 往下读。

---

# 给人类

## 30 秒理解

复现一个场景级 bug，最难的一步不是修，是**到达现场**：登录、选服、点进某个界面、等一场战斗打到第 N 回合。
这步通常只能靠人手点，AI 只能在旁边等。

这个项目把那一步自动化了：

```
  AI / 脚本                        Unity 编辑器
      │                                 │
      │  写 Temp/xxx_cmd.json           │
      ├────────────────────────────────►│  AgentBridge 轮询(0.5s)
      │                                 │  反射分发到 [BridgeAction] 方法
      │  读 Temp/xxx_result.json        │
      │◄────────────────────────────────┤  同步执行，回写结果
      ▼                                 ▼
   拿到 state → 断言 → 下一步       游戏已在目标现场
```

**核心设计：框架固定，场景库随问题生长。**

不预置一堆 API，而是让 AI 遇到具体问题时，**按那个问题的代码逻辑现场加一个最直达的 action**。
加一个方法就是一个新能力，编译后立刻可用。

## 为什么值得用

| 没有它 | 有它 |
|---|---|
| 人点 10 分钟到现场，AI 才能开始查 | AI 自己 1 分钟到现场 |
| 每次复现都要重走一遍热身流程 | 跑通的链路存成 recipe，下次直接回放 |
| AI 只能对着代码猜 | AI 能读到真实运行时状态 |
| 改完代码，验证还得靠人 | AI 自己改 → 自己复现 → 自己验证 |

## 快速开始

### 1. 把 Unity 侧脚本放进工程

复制 `unity/Assets/Editor/AgentBridge/` 到你工程的 `Assets/Editor/` 下。

> 放 `Editor/` 下 → 只在编辑器编译，**不会进正式包**。
> 依赖 `Newtonsoft.Json`（Unity 2018+ 一般已内置；没有就 Package Manager 装 `com.unity.nuget.newtonsoft-json`）。

编辑器 Console 出现这行就是好了：

```
[AgentBridge] 已就绪 (prefix=agentbridge)。监听: <工程>/Temp/agentbridge_cmd.json
```

### 2. 用命令行驱动它

```bash
export AGENTBRIDGE_PROJECT=/path/to/UnityProject   # 省得每次都写 --project

python tools/bridge.py actions                     # 看有哪些 action
python tools/bridge.py send ping
```

```json
{
  "ok": true,
  "action": "ping",
  "state": { "message": "pong", "unityVersion": "2020.3.27f1" }
}
```

### 3. 交给你的 AI agent

把 [`AGENTS.md`](AGENTS.zh-CN.md) 喂给你的 agent（Claude Code / Cursor / 自建 agent 都行）。

## 日常长什么样

假设要给"某场战斗第 5 回合的 buff 显示错乱"写个复现：

```bash
# agent 读代码，发现入场入口是 LoginManager，于是在 BridgeActions.cs 里加：

#   [BridgeAction("enter_battle")]
#   public static JObject EnterBattle(int battleId, int round, int seed = 0) { ... }

# 编译完后驱动：
python tools/bridge.py session clear                       # 开始记录
python tools/bridge.py send play
python tools/bridge.py send login --arg account=test01 --arg password=xxx
python tools/bridge.py send select_server --arg serverId=1001
python tools/bridge.py send enter_battle --arg battleId=100001 --arg round=5 --arg seed=12345
```

```json
{
  "ok": true,
  "action": "enter_battle",
  "state": {
    "round": 5, "leftHp": 48200, "rightHp": 51300,
    "buffs": [ { "id": 34, "stack": 2, "remainMs": 3200 } ]
  }
}
```

拿到状态就能断言，配合 `bridge.py log` 读编辑器日志定位。

**跑通之后别浪费**：

```bash
python tools/bridge.py recipe save battle-100001-r5             # 固化这条链路
python tools/bridge.py recipe run battle-100001-r5              # 以后一条命令回放
python tools/bridge.py recipe run battle-100001-r5 --from 4     # 或只复用后半段
```

## 配套建议：用代码图谱找代码，用本工具到现场

两者分工很干净：

- **代码图谱负责「找到」** —— 这个面板谁在打开、这个 VO 定义在哪、谁调用了这个方法
- **本工具负责「到达」** —— 把游戏开到那个状态，再读回运行时数据

**为什么需要它**：本工具的价值，取决于 agent 能不能快速搞清「现场是怎么到达的」，
而那一步全靠读代码。在大型 Unity 工程里 `grep` 是陷阱：`Assets/` 巨大、同名类遍地、
字符串匹配经常被注释和字面量命中 —— 一次搜索吐回几十个文件把上下文吃光，还未必找对。

### 推荐：[codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)

把代码库索引成**持久知识图谱**，而不是每次现搜：

- 基于 tree-sitter AST 覆盖 160+ 种语言，再用 **Hybrid LSP** 做语义类型解析（**包含 C#**）
- 产出函数、类、调用链、HTTP 路由、跨服务引用的图谱
- 15 个 MCP 工具：搜索、调用链追踪、架构总览、影响面分析、Cypher 查询、死代码检测
- **原生二进制、零依赖**（不需要 Docker / 语言运行时 / API key），全部本地处理
- 自带 3D 图谱可视化（`localhost:9749`）

官方基准称：5 次结构查询约 **3,400 token**，而逐文件搜索约 **412,000 token**。

装上之后，agent 的第 ① 步（读代码搞清路径）就从「翻半天文件」变成「查一次图谱」，
省下的全是 token 和时间。

> 这只是**建议**。如果你把 `AGENTS.md` 交给了 agent，它被要求在相关时会主动向你提这一条，
> **装不装由你决定** —— 它不该擅自安装，也不该因此卡住不动。

---

## 这东西算什么？（Skill / MCP / 本工具）

**一句话：MCP 是「你先把工具做好给 agent 用」；本工具是「agent 自己造工具」。**

| 维度 | Skill | MCP | **本工具** |
|---|---|---|---|
| 本质 | 知识 / 规程 | 工具协议 | 工具 + 规程 |
| **能力由谁定义** | 写 skill 的人 | 写 server 的人 | **agent 自己，运行时生长** |
| **加一个能力要做什么** | 改 `SKILL.md` | 改 server 代码 → 重新部署 → 客户端重连 | **写一个 C# 方法 → 等编译** |
| **能力集何时定型** | 加载时 | server 启动时 | **事先不定型，跟着问题走** |
| 能否执行 | ❌ 不能，只教怎么做 | ✅ | ✅ |
| 传输方式 | 加载进上下文 | JSON-RPC（stdio / HTTP） | 文件协议 + 命令行 |
| 宿主门槛 | 支持 skill 的客户端 | 支持 MCP 的客户端 | 任何能跑命令的 agent |
| 典型用途 | 传授判断力与流程 | 稳定、通用的工具（查库 / 发 HTTP / 读文件） | 项目内、随问题变化的探查能力 |

### 为什么「agent 自己加 action」是本质差别

调试 bug 时要到达的状态**事先无法枚举** —— 你不可能预先把「某场战斗第 5 回合、带 2 层光环 buff、左边血量低于 30%」写成一个 MCP 工具。

**MCP 的工具集是固化的**：想加一个工具，就得改 server 代码、重新部署、让客户端重连。而这里 agent 读完代码就能写一个方法，Unity 编译完能力就有了 —— **工具集是活的**。

这也是为什么本项目里 `AGENTS.md` 花了大量篇幅讲「怎么加 action」而不是「有哪些 action」。

### 那 MCP 什么时候更合适

能力集**已知且稳定**、并且**跨项目复用**的场景：读数据库、发 HTTP、操作文件系统。
这些正适合固化成工具。另外 MCP 不依赖 shell，在禁用命令行的沙箱里反而是唯一选择。

### Skill 呢

Skill 不执行任何东西，它的价值在传授**判断力**：什么时候该加 action、为什么不能模拟点击、
卡住了先量 `frame` 而不是猜网络。本项目的 `AGENTS.md` + `docs/` 就是这部分 ——
它是 skill 的现成素材，可以直接打包成一个 skill。

**建议**：常态用 CLI；想把判断力交给 agent 就打成 skill；
只有遇到「必须固化 + 跨项目复用 + 无 shell」的场景才上 MCP。

## 适合 / 不适合

**适合**：编辑器内的场景级复现、状态断言、批量回归、给 AI 提供"能到达现场"的能力。

**不适合**：真机验证、UI 交互手感、渲染表现、需要真实点击/输入的体验测试。
那些属于 OS 层自动化（截图 + 坐标点击）的范畴，两者互补而非替代。

## ⚠️ 一个必须知道的坑

**Unity 编辑器一旦失去 OS 焦点，播放循环会「完全停摆」**——不是降速，是彻底不走帧。

实测：失焦 115 秒内 `Time.frameCount` 一直是 **2**；重新聚焦后 6 秒到 203。

后果很隐蔽：所有靠 `MonoBehaviour.Update` 驱动的异步系统（资源加载、协程、网络回调）会一起卡死，
**表象极像网络问题或资源加载失败**。文件驱动的 agent 天然处于失焦状态，必踩。

两个反直觉点（都实测过）：

- `PlayerSettings.runInBackground = true` **对编辑器播放循环无效**
- `Application.isFocused` **不可靠**——失焦时它仍返回 `true`

`play` 动作已内置自动抢焦点作为对策。完整分析见 [`docs/pitfalls.md`](docs/pitfalls.zh-CN.md)。

## 目录结构

```
unity-agent-bridge/
├── README.md                       # 英文版（开源默认）
├── README.zh-CN.md                 # 你正在看的（人类部分 + agent 部分）
├── AGENTS.md                       # ⭐ 交给 AI agent 的完整规则（英文）
├── AGENTS.zh-CN.md                 # 同上，中文版
├── docs/                           # 每篇都有 xxx.md（英文）+ xxx.zh-CN.md（中文）
│   ├── architecture.md             文件协议、分发机制、与 batchmode 的关系
│   ├── adding-actions.md           ⭐ 怎么动态加 action
│   ├── recipes.md                  链路保存与复用
│   ├── pitfalls.md                 踩过的坑（失焦停摆排第一）
│   └── open-sourcing.md            加项目内容前的脱敏清单
├── unity/Assets/Editor/AgentBridge/
│   ├── AgentBridge.cs              骨架：轮询 / 分发 / 自动抢焦点
│   └── BridgeActions.cs            ⭐ agent 实时编辑的文件（只放通用能力）
└── tools/
    ├── bridge.py                   命令行驱动
    └── recipes/                    链路库
```

> **关于语言**：文档约定与 GitHub 惯例一致 —— 主名放英文，中文加 `.zh-CN.md` 后缀。
> 每篇文档标题下都有一行切换链接。

## 常见问题

**Q：一定要用 Python 吗？**
不用。`bridge.py` 只是把文件协议包成了好用的命令。协议本身就是两个 JSON 文件，
任何语言、甚至手工 `echo` 都能驱动。

**Q：能跟别的工具/agent 并存吗？**
能。`--prefix`（或环境变量 `AGENTBRIDGE_PREFIX`）隔离各自的指令文件。

**Q：项目专有的 action 会进这个仓库吗？**
不会。`BridgeActions.cs` 只放通用能力，项目专属请另建文件（同样打 `[BridgeAction]` 就会被发现），
这样两边能各自独立升级。

**Q：和 EditMode 测试什么关系？**
互补。编辑器**关着**时跑 EditMode 测试（快、适合纯逻辑）；编辑器**开着**时用本项目（能到场景现场）。
两者互斥，不能同时开。

---

# 给 AI agent

> 完整规则见 [`AGENTS.md`](AGENTS.zh-CN.md)。这里是精简版，够你开工。

## 硬性规则

1. **不要模拟人的点击。** 加 action 要「一步到位」直达现场，不是 `click(100,200)` 点过去。
   点坐标属于 OS 层自动化的活。
2. **加 action 前先读代码。** 搞清"这个现场正常玩是怎么走到的"，照那条真实路径写。
   **猜出来的路径会把你带到错误状态，比到不了更糟。**
3. **涉及随机的场景必须支持传随机种子。** 不然 bug 复现不出来。
4. **返回关键状态。** 返回值是你的断言依据，比看截图可靠。
5. **只加读，慎加写**，且**不要**加通用的「执行任意方法」反射接口 —— 不可审计、不可复用。
6. **项目专有的 action 单独放文件**，别混进 `BridgeActions.cs`。

## 标准工作流

```
① 读代码      → 搞清「怎样才能到达那个现场」
② 加 action   → 在 BridgeActions.cs 里写一个最直达的方法
③ 编译        → Unity 自动编译，几秒
④ 驱动        → bridge.py send <action> --arg k=v ...
⑤ 读状态+日志 → bridge.py send ... / bridge.py log --tail 100
⑥ 定位→改代码 → 回到 ③
⑦ 跑通了      → bridge.py recipe save <名字>
```

## 加一个 action

```csharp
/// <summary>直接到达「某场战斗的第 N 回合」</summary>
[BridgeAction("enter_battle")]
public static JObject EnterBattle(int battleId, int round, int seed = 0)
{
    // 1. 按项目里真实的入场路径把游戏送到目标现场
    // 2. seed != 0 时固定随机，保证可复现
    // 3. 返回关键状态供断言
    return new JObject { ["ok"] = true, ["round"] = round, ["leftHp"] = ..., ["buffs"] = new JArray(...) };
}
```

- `public static`，返回 `JObject`；参数支持 `int`/`float`/`bool`/`string`，名字对应 `--arg k=v`
- `[BridgeAction("名字")]` **自动被发现，不需要注册**
- 命名：`动词_对象`（`enter_battle`、`set_hero_level`）

> **找真实路径的技巧**：很多项目自带开发者/调试面板（快速登录、跳关、发道具），
> 它们已经帮你找好了最短路径，**照抄它们的调用方式**最省事也最正确。

## 卡住了？先量循环活没活

```bash
python tools/bridge.py send frame      # 隔几秒再发一次，比对 frameCount
```

- `frameCount` 在涨 → 循环正常，是**逻辑问题**，去读日志
- `frameCount` 不动 → **循环被挂起了**（编辑器失焦 / 暂停 / 正在编译）。
  此时所有异步系统都不推进，**你看到的一切"异常"都是假象**

> **别在没有 `frame` 证据的情况下断言"是网络问题 / 资源问题"。**

## 复用跑通的链路

```bash
python tools/bridge.py session clear                   # 开始前清一次
# ... 正常驱动 ...
python tools/bridge.py recipe save my-flow             # 跑通后固化
python tools/bridge.py recipe run my-flow              # 整条回放
python tools/bridge.py recipe run my-flow --from 3     # 只复用后半段
```

保存后手工补两样（自动生成给不了）：**`wait`/`expect` 等待条件**、**seed 固定随机**。
写法见 [`docs/recipes.md`](docs/recipes.zh-CN.md)。

> ⚠️ **recipe 是私有资产**，里面有账号、服务器 ID、业务流程 —— **不要提交到公开仓库**。

## 别做这些

- ❌ 为了让"一步到位"而绕过真实业务路径硬塞状态 —— 复现出来的不是真 bug
- ❌ 加 `invoke(type, method, args)` 这种通用反射接口
- ❌ 把项目专有逻辑写进 `BridgeActions.cs`
- ❌ 没有 `frame` 证据就说"是网络/资源问题"
- ❌ 把带凭据的 recipe 推到公开仓库

---

## License

[MIT](LICENSE)
