# unity-agent-bridge

**让 AI agent 自己把 Unity 游戏开到出问题的那一幕，读完状态再回来改代码。**

复现一个场景级 bug，最难的一步不是修，是**到达现场**：登录、选服、点进某个界面、等一场战斗打到第 N 回合。
这一步通常只能靠人手点，AI 只能在旁边等。

这个项目把那一步自动化了：AI 通过一个文件协议驱动 Unity 编辑器，把游戏送到指定状态、读回运行时数据，
然后看日志、定位、改代码、再来一遍 —— 形成闭环。

---

## 它长什么样

```
  AI / 脚本                        Unity 编辑器
      │                                 │
      │  写 Temp/xxx_cmd.json           │
      ├────────────────────────────────►│  AgentBridge 轮询(0.5s)
      │                                 │  反射分发到 [BridgeAction] 方法
      │  读 Temp/xxx_result.json        │
      │◄────────────────────────────────┤  同步执行，回写结果
      │                                 │
      ▼                                 ▼
   拿到 state → 断言 → 继续下一步   游戏已在目标现场
```

**核心设计：框架固定，场景库随问题生长。**

不预置一堆 API，而是让 AI 在遇到具体问题时，**按那个问题的代码逻辑现场加一个最直达的 action**。
加一个方法就是一个新能力，编译后立刻可用。

---

## 快速开始

### 1. 把 Unity 侧脚本放进工程

复制 `unity/Assets/Editor/AgentBridge/` 到你工程的 `Assets/Editor/` 下。

> 放在 `Editor/` 下 → 只在编辑器编译，**不会进正式包**。
> 依赖 `Newtonsoft.Json`（Unity 2018+ 一般已内置；没有的话 Package Manager 装 `com.unity.nuget.newtonsoft-json`）。

启动编辑器，Console 出现这行就对了：

```
[AgentBridge] 已就绪 (prefix=agentbridge)。监听: <工程>/Temp/agentbridge_cmd.json
```

### 2. 用命令行驱动它

```bash
python tools/bridge.py --project /path/to/UnityProject actions
```

输出当前已注册的所有 action。然后：

```bash
$ python tools/bridge.py --project /path/to/UnityProject send ping
{
  "ok": true,
  "action": "ping",
  "state": { "message": "pong", "unityVersion": "2020.3.27f1" }
}
```

也可以设成环境变量省掉 `--project`：

```bash
export AGENTBRIDGE_PROJECT=/path/to/UnityProject
python tools/bridge.py send ping
```

### 3. 让 AI 用起来

把仓库里的 [`AGENTS.md`](AGENTS.md) 交给你的 AI agent（Claude Code / Cursor / 自建 agent 都行），
它写明了 agent 该遵守的工作流和加 action 的规则。

---

## 内置 action

通用能力都在 `BridgeActions.cs` 里，跟具体项目无关：

| action | 作用 | 参数 |
|---|---|---|
| `ping` | 验证链路 | — |
| `list_actions` | 列出所有已注册 action | — |
| `editor_info` | 播放状态 / 当前场景 / 是否 dirty | — |
| `play` / `stop` | 进出播放模式 | — |
| `pause` | 暂停/恢复 | `paused` |
| `focus` | 把编辑器窗口拉回前台 | — |
| `frame` | **播放循环探针**（排查"卡住了"第一步就调它） | — |
| `set_run_in_background` | 读写后台运行开关 | `enabled` |
| `open_scene` / `list_scenes` | 打开 / 列出场景 | `scene` |
| `probe` | **只读**探针：按类型名读静态成员或单例成员 | `type` / `member` / `via` |

**项目专属的 action 请另建文件**（同样打 `[BridgeAction]` 即可被发现），
这样通用能力可以独立升级，也便于把项目内容排除在开源之外。

---

## 链路复用（recipe）

跑通一条链路后，把成功的那几步固化下来，下次直接回放：

```bash
# 1. 开始一轮新复现前先清空记录
python tools/bridge.py session clear

# 2. 正常驱动，每一步都会自动记进 session
python tools/bridge.py send play
python tools/bridge.py send enter_battle --arg battleId=1001 --arg seed=42

# 3. 跑通后存成 recipe
python tools/bridge.py recipe save enter-battle-1001

# 4. 以后整条回放
python tools/bridge.py recipe run enter-battle-1001

# 5. 或者只复用其中一段
python tools/bridge.py recipe run enter-battle-1001 --from 3
```

详见 [`docs/recipes.md`](docs/recipes.md)。

---

## ⚠️ 一个必须知道的坑

**Unity 编辑器一旦失去 OS 焦点，播放循环会「完全停摆」**——不是降速，是彻底不走帧。

实测：失焦 115 秒内 `Time.frameCount` 一直是 **2**；重新聚焦后 6 秒到 203。

后果很隐蔽：所有靠 `MonoBehaviour.Update` 驱动的异步系统（资源加载、协程、网络回调）
会一起卡死，**表象极像网络问题或资源加载失败**。文件驱动的 agent 天然处于失焦状态，必踩。

两个反直觉点（都验证过）：

- `PlayerSettings.runInBackground = true` **对编辑器播放循环无效**
- `Application.isFocused` **不可靠** —— 失焦时它仍然返回 `true`

`play` 动作已内置自动抢焦点作为对策。完整分析见 [`docs/pitfalls.md`](docs/pitfalls.md)。

---

## 目录结构

```
unity-agent-bridge/
├── AGENTS.md                       # ⭐ 交给 AI agent 的规则入口
├── docs/
│   ├── architecture.md             # 文件协议与分发机制
│   ├── adding-actions.md           # ⭐ 怎么动态加 action
│   ├── recipes.md                  # 链路保存与复用
│   ├── pitfalls.md                 # 踩过的坑（含失焦停摆实测）
│   └── open-sourcing.md            # 加项目内容前的脱敏清单
├── unity/Assets/Editor/AgentBridge/
│   ├── AgentBridge.cs              # 稳定骨架：轮询 / 分发 / 自动抢焦点
│   └── BridgeActions.cs            # ⭐ agent 实时编辑的文件（只放通用能力）
└── tools/
    ├── bridge.py                   # 命令行驱动
    └── recipes/                    # 链路库
```

---

## 适用边界

**适合**：编辑器内的场景级复现、状态断言、批量回归、给 AI 提供"能到达现场"的能力。

**不适合**：真机验证、UI 交互手感、渲染表现、需要真实点击/输入的体验测试。
那些属于 OS 层自动化（截图 + 坐标点击）的范畴，两者互补而非替代。

---

## License

[MIT](LICENSE)
