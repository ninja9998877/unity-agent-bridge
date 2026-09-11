# unity-agent-bridge

**Let your AI agent drive Unity to the exact moment a bug happens — then read real runtime state and get to work.**

[English](README.md) | [简体中文](README.zh-CN.md)

`Unity 2019+` · `AI Agent` · `Scene-level repro` · `MIT`

---

> **🤖 AI agent?** Jump straight to [**For AI agents**](#for-ai-agents) — that's your working spec. Read it before doing anything.
>
> **👤 Human?** Keep reading.

---

# For humans

## The 30-second version

When you reproduce a scene-level bug, the hard part isn't the fix — it's **getting there**:
log in, pick a server, navigate into a screen, wait for a battle to reach round N.
That step is usually manual, and the AI just sits there waiting.

This project automates that step.

```
  AI / script                       Unity Editor
      │                                  │
      │  write Temp/xxx_cmd.json         │
      ├─────────────────────────────────►│  AgentBridge polls (0.5s)
      │                                  │  dispatches by reflection to [BridgeAction]
      │  read Temp/xxx_result.json       │
      │◄─────────────────────────────────┤  runs synchronously, writes result back
      ▼                                  ▼
   read state → assert → next step    the game is now in the target state
```

**Core idea: the framework is fixed, the scenario library grows as you hit problems.**

Instead of shipping a pile of pre-built APIs, the agent — when it hits a specific problem —
**reads the code and adds the one action that jumps straight to that exact state.**
One new method is one new capability, available as soon as Unity compiles.

## Why bother

| Without it | With it |
|---|---|
| A human clicks for 10 minutes before the AI can start | The AI gets there itself in about a minute |
| Every repro re-walks the same warm-up steps | Proven chains are saved as recipes and replayed |
| The AI can only guess from source code | The AI reads real runtime state |
| After a fix, a human still has to verify | The AI reproduces, verifies, and iterates on its own |

## Quick start

### 1. Drop the Unity scripts into your project

Copy `unity/Assets/Editor/AgentBridge/` into your project's `Assets/Editor/`.

> Under `Editor/` → editor-only compilation, **never shipped in a build**.
> Requires `Newtonsoft.Json` (bundled with Unity 2018+; otherwise install
> `com.unity.nuget.newtonsoft-json` from the Package Manager).

You're good when the Console shows:

```
[AgentBridge] 已就绪 (prefix=agentbridge)。监听: <project>/Temp/agentbridge_cmd.json
```

### 2. Drive it from the command line

```bash
export AGENTBRIDGE_PROJECT=/path/to/UnityProject   # so you can drop --project

python tools/bridge.py actions                     # list available actions
python tools/bridge.py send ping
```

```json
{
  "ok": true,
  "action": "ping",
  "state": { "message": "pong", "unityVersion": "2020.3.27f1" }
}
```

### 3. Hand it to your AI agent

Feed [`AGENTS.md`](AGENTS.md) to your agent (Claude Code, Cursor, a homegrown agent — anything works).

## What it looks like day to day

Say you need to reproduce "buffs render wrong on round 5 of battle X":

```bash
# The agent reads the code, finds the entry point is LoginManager, and adds to BridgeActions.cs:

#   [BridgeAction("enter_battle")]
#   public static JObject EnterBattle(int battleId, int round, int seed = 0) { ... }

# Once compiled, it drives the game:

python tools/bridge.py session clear                       # start recording
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

With structured state in hand it can assert; `bridge.py log` tails the editor log for the rest.

**Don't throw away a working chain:**

```bash
python tools/bridge.py recipe save battle-100001-r5             # freeze it
python tools/bridge.py recipe run battle-100001-r5              # replay the whole thing later
python tools/bridge.py recipe run battle-100001-r5 --from 4     # or just reuse the tail
```

## Recommended pairing: a code graph to *find* code, this tool to *reach* the scene

The division of labour is clean:

- **The code graph finds things** — who opens this panel, where this VO is defined, who calls this method
- **This tool reaches things** — drives the game into that state and reads back runtime data

**Why you want both**: the value of this tool depends on how fast the agent can figure out *how to
reach* a state — and that step is all about reading code. On a large Unity project `grep` is a trap:
a huge `Assets/` tree, same-named classes everywhere, string matches hitting comments and literals.
One search dumps dozens of files into your context, burns tokens, and may still be wrong.

### Recommendation: [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)

It indexes your codebase into a **persistent knowledge graph** instead of searching fresh every time:

- tree-sitter AST across 160+ languages, plus **Hybrid LSP** semantic type resolution (**including C#**)
- A graph of functions, classes, call chains, HTTP routes and cross-service references
- 15 MCP tools: search, call-chain tracing, architecture overview, impact analysis, Cypher queries, dead-code detection
- **Native binary, zero dependencies** (no Docker, no language runtime, no API key), all processing local
- Built-in 3D graph visualization at `localhost:9749`

Their own benchmark: 5 structural queries cost about **3,400 tokens** versus roughly **412,000**
for file-by-file search.

With it installed, the agent's step ① ("read the code to find the path") goes from paging through
files to one graph query — and the savings are all tokens and wall-clock.

---

## What is this, exactly? (Skill / MCP / this tool)

**One line: MCP is "you build the tools first, then the agent uses them"; this tool is "the agent builds its own tools".**

| | Skill | MCP | **This tool** |
|---|---|---|---|
| Nature | Knowledge / procedure | Tool protocol | Tool + procedure |
| **Who defines capabilities** | Whoever writes the skill | Whoever writes the server | **The agent itself, growing at runtime** |
| **To add one capability** | Edit `SKILL.md` | Edit server code → redeploy → client reconnects | **Write one C# method → wait for compile** |
| **When the toolset is fixed** | At load time | At server startup | **Never — it follows the problem** |
| Can it execute? | ❌ No, it only teaches | ✅ | ✅ |
| Transport | Loaded into context | JSON-RPC (stdio / HTTP) | File protocol + CLI |
| Host requirement | A client that supports skills | A client that supports MCP | Any agent that can run commands |
| Typical use | Teaching judgment and process | Stable, generic tools (DB, HTTP, filesystem) | Project-local, problem-specific probing |

### Why "the agent adds its own actions" is the essential difference

The states you need to reach while debugging **cannot be enumerated in advance** — you can't
pre-write an MCP tool for "round 5 of battle X, two stacks of aura buff, left side under 30% HP".

**An MCP toolset is frozen**: adding a tool means editing the server, redeploying, and having the
client reconnect. Here, the agent reads the code and writes a method; once Unity compiles, the
capability exists. **The toolbox is alive.**

That's also why `AGENTS.md` spends most of its length on "how to add an action" rather than
"here are the actions".

### So when is MCP the better fit?

When the capability set is **known, stable, and reused across projects**: reading a database,
making HTTP calls, manipulating the filesystem. Those are exactly right to freeze into tools.
MCP also doesn't depend on a shell, which makes it the only option in sandboxes that disable commands.

### And skills?

A skill executes nothing. Its value is teaching **judgment**: when to add an action, why not to
simulate clicks, why to measure `frame` before blaming the network. This project's `AGENTS.md` +
`docs/` *are* that material — ready to be packaged as a skill as-is.

**Recommendation**: use the CLI by default; package a skill when you want to hand over the judgment;
reach for MCP only when you need "frozen + cross-project + no shell".

## Good fit / bad fit

**Good fit**: scene-level repro inside the editor, state assertions, batch regression,
giving an AI the ability to reach the scene at all.

**Bad fit**: on-device verification, UI feel, rendering, anything needing real clicks or typing.
That's the domain of OS-level automation (screenshot + coordinate clicking). The two are
complementary, not competing.

## ⚠️ One gotcha you must know

**Once the Unity Editor loses OS focus, the play loop stops completely** — not slows down, *stops*.

Measured: `Time.frameCount` stayed at **2** for 115 seconds while unfocused; after refocusing it
reached 203 within 6 seconds.

The fallout is subtle: every async system driven by `MonoBehaviour.Update` (asset loading,
coroutines, network callbacks) freezes along with it, so it **looks exactly like a network
problem or a failed asset download**. A file-driven agent is unfocused by nature, so it will always hit this.

Two counter-intuitive facts (both verified):

- `PlayerSettings.runInBackground = true` **has no effect** on the editor play loop
- `Application.isFocused` **is unreliable** — it still returns `true` while unfocused

The `play` action auto-refocuses the window as a countermeasure.
Full analysis in [`docs/pitfalls.md`](docs/pitfalls.md).

## Layout

```
unity-agent-bridge/
├── README.md                       # this file (English)
├── README.zh-CN.md                 # 简体中文
├── AGENTS.md                       # ⭐ the full spec you hand to an AI agent
├── AGENTS.zh-CN.md                 # same, in Chinese
├── docs/                           # every doc has xxx.md (EN) + xxx.zh-CN.md (ZH)
│   ├── architecture.md             file protocol, dispatch, relation to batchmode
│   ├── adding-actions.md           ⭐ how to add actions on the fly
│   ├── recipes.md                  saving and reusing chains
│   ├── pitfalls.md                 the pits we fell into (play-loop stall is #1)
│   └── open-sourcing.md            scrub checklist before open-sourcing
├── unity/Assets/Editor/AgentBridge/
│   ├── AgentBridge.cs              skeleton: polling / dispatch / auto-refocus
│   └── BridgeActions.cs            ⭐ the file the agent edits live (generic actions only)
└── tools/
    ├── bridge.py                   command-line driver
    └── recipes/                    the chain library
```

> **On languages**: following GitHub convention, the canonical filename is English and Chinese
> versions carry a `.zh-CN.md` suffix. Every document has a switcher link under its title.

## FAQ

**Does it have to be Python?**
No. `bridge.py` just wraps the file protocol into convenient commands. The protocol itself is
two JSON files — any language works, even `echo`.

**Can it coexist with other tools/agents?**
Yes. Use `--prefix` (or `AGENTBRIDGE_PREFIX`) to isolate each one's command files.

**Will my project-specific actions end up in this repo?**
No. `BridgeActions.cs` holds generic capabilities only. Put project-specific ones in a separate
file (same `[BridgeAction]` attribute, auto-discovered), so the two can evolve independently.

**How does this relate to EditMode tests?**
Complementary. With the editor **closed**, run EditMode tests (fast, pure logic). With the editor
**open**, use this project (reaches actual scene state). They're mutually exclusive — only one
Unity instance per project.

---

# For AI agents

> The full spec is in [`AGENTS.md`](AGENTS.md). This is the short version — enough to start.

## Hard rules

1. **Don't simulate human clicks.** Add an action that jumps **straight** to the target state,
   not `click(100,200)` sequences. Coordinate clicking is OS-level automation's job.
2. **Read the code before adding an action.** Figure out *how the game normally gets there*,
   then follow that real path. **A guessed path lands you in a wrong state — worse than not arriving.**
3. **Anything random must accept a seed.** Otherwise the bug won't reproduce.
4. **Return meaningful state.** Your return value is the assertion basis — far more reliable than a screenshot.
5. **Prefer reads over writes**, and **never** add a generic "invoke any method" reflection endpoint —
   it's unauditable and unreusable.
6. **Keep project-specific actions in a separate file**, out of `BridgeActions.cs`.

## Standard workflow

```
① Read the code  → figure out how to reach the target state
② Add an action  → one straight-to-the-point method in BridgeActions.cs
③ Compile        → Unity recompiles automatically, a few seconds
④ Drive          → bridge.py send <action> --arg k=v ...
⑤ Read state+log → bridge.py send ... / bridge.py log --tail 100
⑥ Locate → fix   → back to ③
⑦ Chain works    → bridge.py recipe save <name>
```

## Adding an action

```csharp
/// <summary>Jump straight to "round N of battle X"</summary>
[BridgeAction("enter_battle")]
public static JObject EnterBattle(int battleId, int round, int seed = 0)
{
    // 1. Follow the project's real entry path to put the game in the target state
    // 2. Fix the RNG when seed != 0, so it's reproducible
    // 3. Return the state you'll assert on later
    return new JObject { ["ok"] = true, ["round"] = round, ["leftHp"] = ..., ["buffs"] = new JArray(...) };
}
```

- `public static`, returns `JObject`; params may be `int`/`float`/`bool`/`string`, matching `--arg k=v`
- `[BridgeAction("name")]` is **auto-discovered — no registration**
- Naming: `verb_object` (`enter_battle`, `set_hero_level`)

> **Tip for finding the real path**: many projects ship a developer/debug panel (fast login,
> level skip, grant item). Those already found the shortest path — **copy how they call it.**

## Stuck? Measure whether the loop is alive first

```bash
python tools/bridge.py send frame      # send it twice a few seconds apart, compare frameCount
```

- `frameCount` increasing → the loop is fine; this is a **logic problem**, go read the log
- `frameCount` frozen → **the loop is suspended** (editor unfocused / paused / compiling).
  Nothing async advances, so **every "anomaly" you see is an illusion**

> **Never claim "it's a network/resource problem" without `frame` evidence.**

## Reusing a chain that worked

```bash
python tools/bridge.py session clear                   # clear before starting
# ... drive normally ...
python tools/bridge.py recipe save my-flow             # freeze it once it works
python tools/bridge.py recipe run my-flow              # replay the whole thing
python tools/bridge.py recipe run my-flow --from 3     # or reuse only the tail
```

After saving, hand-edit two things the generator can't produce:
**`wait`/`expect` conditions**, and **a fixed seed** for anything random.
Syntax in [`docs/recipes.md`](docs/recipes.md).

> ⚠️ **Recipes are private assets.** They contain accounts, server IDs, and business flows —
> **never commit them to a public repo.**

## Don't do these

- ❌ Bypass the real code path and force state in, just to "jump straight there" — the bug you
  reproduce won't be the real bug
- ❌ Add a generic `invoke(type, method, args)` reflection endpoint
- ❌ Put project-specific logic into `BridgeActions.cs`
- ❌ Claim "it's a network/resource problem" without `frame` evidence
- ❌ Push recipes containing credentials to a public repo

---

## License

[MIT](LICENSE)
