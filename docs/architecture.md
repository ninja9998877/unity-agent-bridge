# 架构与协议

## 为什么用文件轮询

也考虑过 socket / HTTP / named pipe，最终选文件轮询，理由：

| | 文件轮询 | socket / HTTP |
|---|---|---|
| Unity 侧依赖 | **零**（`System.IO`） | 需要监听线程 / 协程，还要处理端口占用、防火墙 |
| 崩溃恢复 | 文件被占用就下次再读，天然幂等 | 连接断开要重连、要处理半包 |
| 可观测 | 打开文件就能看，出问题好排查 | 要抓包 |
| 跨平台 | 无差异 | 各平台权限/防火墙策略不同 |

代价是 **0.5 秒轮询延迟**——对"驱动游戏到某个场景"这个量级的操作完全够用。
需要毫秒级交互（比如做实时同步）时，这套设计不合适。

---

## 两个文件，一个循环

```
<ProjectRoot>/Temp/<prefix>_cmd.json       ← 外部写，Unity 读
<ProjectRoot>/Temp/<prefix>_result.json    ← Unity 写，外部读
```

放 `Temp/` 的原因：Unity 的临时目录，**不纳入版本控制**，也不会被打进包。

`<prefix>` 默认 `agentbridge`，可用环境变量 `AGENTBRIDGE_PREFIX` 覆盖。
需要和别的桥（或同一工程的多个 agent）并存时用它隔离。

### 指令格式

```json
{ "action": "probe", "args": { "type": "GameStateManager", "member": "curState" } }
```

### 结果格式

```json
{
  "ok": true,
  "action": "probe",
  "state": { "value": "GS_CITY" }
}
```

失败时：`{"ok": false, "action": "...", "error": "..."}`。
未知 action 时会额外返回 `available` 数组，便于自纠。

---

## Unity 侧的循环

`AgentBridge`（`[InitializeOnLoad]`）挂在 `EditorApplication.update` 上：

```
每帧被调用
  ├─ KeepLoopAlive()      播放模式下检测帧循环停摆 → 自动抢焦点
  └─ 距上次轮询 ≥ 0.5s ?
       ├─ cmd 文件存在？
       │    ├─ 读内容 → 【先删文件】（防止同一条指令被执行两次）
       │    ├─ 解析 JSON
       │    ├─ 反射找 [BridgeAction(name)] 方法
       │    ├─ 按参数名构造实参（int/float/bool/string）
       │    ├─ 同步 Invoke
       │    └─ 结果写 result 文件
       └─ 否则跳过
```

**要点**：

- **读完立刻删** `cmd` 文件。否则外部写一次、Unity 执行两次。
- **同步执行**。action 必须是"当场就能做完"的操作。跨帧的（等资源加载完、等动画播完）
  不能写成 action，应该由外部多次轮询状态来实现。
- **`_busy` 重入保护**。action 执行期间不处理新指令。

---

## action 的发现

不需要注册表。反射扫描 `AgentBridge` 命名空间下所有 `public static` 方法，
取带 `[BridgeAction("名字")]` 的。

这意味着：

- **加一个 action = 加一个方法**，没有别的仪式
- 可以在**多个文件 / 多个类**里定义 action，只要同命名空间
- 项目专属的 action 建议放独立文件，便于把通用能力和项目内容分开管理

---

## 参数绑定

按**方法参数名**去 `args` 里取值（找不到时再试全小写形式）。

```json
{"action":"foo","args":{"round":5,"seed":42,"hard":true,"label":"x"}}
```

```csharp
public static JObject Foo(int round, int seed = 0, bool hard = false, string label = "")
```

- 类型支持：`int` / `float` / `bool` / `string`
- 没传且参数有默认值 → 用默认值
- 没传且没有默认值 → 该类型的零值（不报错）

---

## 与 Batchmode 的关系

两者**互斥**——Unity 不允许两个实例打开同一工程。

| 编辑器状态 | 能做什么 |
|---|---|
| **关闭** | batchmode：编译校验、EditMode 纯逻辑测试 |
| **打开** | AgentBridge：驱动场景、读运行时状态 |

典型节奏：

```
读代码 / 改代码        （编辑器状态无所谓）
   ↓
关编辑器 → 跑 batchmode 编译校验     ← 快，适合频繁改代码时
   ↓
开编辑器 → 用 AgentBridge 复现       ← 需要场景时
```

---

## 安全边界

- 脚本放 `Assets/Editor/` 下 → **只在编辑器编译，不会进正式包**
- 指令/结果文件在 `Temp/` → 不进版本控制
- **不提供通用的"执行任意方法"接口** —— 所有能力都必须在 actions 文件里显式实现，
  这是刻意的设计：可审计、可复用、可 review
- `probe` 只读，不写、不调方法
