# AGENTS.md — Working rules for AI agents

[English](AGENTS.md) | [简体中文](AGENTS.zh-CN.md)

You're working in a Unity project, and one of your goals is to **reach the scene of a bug yourself**
instead of asking a human to reproduce it for you.

Everything you need is below. **Read it before doing anything.**

---

## 0. Hard rules

1. **Don't simulate human clicks.** An action should jump **straight** to the target state,
   not walk there via `click(100,200)` sequences. Coordinate clicking is OS-level automation's job.
2. **Read the code before adding an action.** Figure out how the game *normally* gets to that state,
   then follow that real path. **A guessed path lands you in a wrong state — worse than not arriving at all.**
3. **Anything random must accept a seed.** Crits, dodges, random targets — without a fixed seed the bug won't reproduce.
4. **Return meaningful state.** Your return value is the assertion basis, and far more reliable than a screenshot.
5. **Prefer reads over writes.** To *drive* something, add an explicit action (auditable, reusable).
   Never add a generic "invoke any method" endpoint.
6. **Keep project-specific actions in a separate file**, out of `BridgeActions.cs` — that file holds
   generic capabilities and must be independently upgradable.

---

## 1. First, check that the bridge is alive

```bash
python tools/bridge.py --project <UnityProjectRoot> actions
```

- Lists actions → you're good
- "Unity isn't responding" → the editor isn't open / scripts haven't finished compiling /
  the Console has no `[AgentBridge] 已就绪` line

Consider setting `AGENTBRIDGE_PROJECT` so you can drop `--project`.

---

## 2. Standard workflow

```
① Read the code  → figure out how to reach the target state
② Add an action  → one straight-to-the-point method in BridgeActions.cs (or your own actions file)
③ Compile        → Unity recompiles automatically, a few seconds
④ Drive          → bridge.py send <action> --arg k=v ...
⑤ Read state+log → bridge.py send <action> / bridge.py log --tail 100
⑥ Locate → fix   → back to ③
⑦ Chain works    → bridge.py recipe save <name>     ← freeze it before you lose it
```

> **On step ①: query a code graph, don't grep.**
> On a large codebase `grep` both burns your context and misleads you — same-named classes, string
> literals and comments all match. Use a symbol/graph-level index instead
> ([codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)) to locate definitions
> and call sites in one query. **The whole workflow's efficiency depends on step ① being cheap.**

---

## 3. How to add an action on the fly

Add a method to `BridgeActions.cs`:

```csharp
/// <summary>Jump straight to "round N of battle X"</summary>
[BridgeAction("enter_battle")]
public static JObject EnterBattle(int battleId, int round, int seed = 0)
{
    // 1. Read the code; follow the project's real entry path into the target state
    // 2. When seed != 0, fix the RNG so it's reproducible
    // 3. Return the state you'll assert on later
    return new JObject
    {
        ["ok"] = true,
        ["round"] = round,
        ["leftHp"] = ...,
        ["rightHp"] = ...,
        ["buffs"] = new JArray(...),
    };
}
```

**Requirements:**

| | |
|---|---|
| Signature | `public static`, returns `JObject` (comes back as `state`) |
| Params | `int` / `float` / `bool` / `string`; names match the command's `args` keys |
| Registration | None — `[BridgeAction("name")]` is auto-discovered |
| Naming | `verb_object`: `enter_battle`, `set_hero_level`, `replay_to_round` |
| Granularity | **Straight to the point.** Reach the target state directly, don't walk the interaction |
| Return value | Include everything you'll want to assert on |
| Randomness | **Must accept a seed** |

**Don't write this:**

```csharp
[BridgeAction("click_login_button")]      // ✗ that's OS-level automation's job
public static JObject ClickLoginButton() { /* simulate one click */ }
```

**Write this:**

```csharp
[BridgeAction("login_as")]                 // ✓ call the real login path
public static JObject LoginAs(string account, string password)
{
    // Call whatever actually handles login (copy how the project's own dev tools do it — that's the safest bet)
}
```

> **Tip for finding the real path**: many projects ship a developer/debug panel (fast login,
> level skip, grant item). Those already found the shortest path — **copy how they call it.**
> They also tend to use reflection for private methods, which means you don't have to touch
> business code at all.

### Why *you* add actions, and not someone else

This is the key difference from MCP-style tooling: **MCP tools are frozen at authoring time;
the agent cannot add one.** Here, the capability set grows at runtime because *you* write the
methods. The set of states you'll need to reach while debugging is not enumerable in advance —
so the toolbox has to grow with the problem. That only works if you actually add the action
you need instead of trying to make do with what's there.

---

## 4. Debugging "it's stuck"

**Your first move is always to measure whether the play loop is alive.** Don't jump to
network/resource theories:

```bash
python tools/bridge.py send frame
# send it again a few seconds later and compare frameCount
```

- `frameCount` increasing → the loop is fine; this is a **logic problem**, go read the log
- `frameCount` frozen → **the loop is suspended** (editor unfocused / paused / compiling).
  Nothing async advances, so **every "anomaly" you see is an illusion**

Details in [`docs/pitfalls.md`](docs/pitfalls.md). This is the single easiest thing to misdiagnose.

---

## 5. Reuse chains that already worked

**Every time a chain works, save it.** Never let the next repro start from zero.

```bash
python tools/bridge.py session clear          # clear before starting
# ... drive normally ...
python tools/bridge.py recipe save my-flow    # freeze it once it works
python tools/bridge.py recipe run my-flow     # replay the whole thing later
python tools/bridge.py recipe run my-flow --from 3   # or reuse only the tail
```

After saving, **hand-edit two things** the generator can't produce:

1. **`wait` / `expect`** — which steps need waiting, and on what condition
2. **seed** — fix the RNG on any step that involves randomness

Syntax, variable substitution and conditional waits: [`docs/recipes.md`](docs/recipes.md).

**Recipes are project-bound assets. Never commit them to a public repo** — they contain
accounts, server IDs and business flows.

---

## 6. Things you must not do

- ❌ Bypass the real code path and force state in, just to "jump straight there" — the bug you
  reproduce won't be the real bug
- ❌ Add a generic reflection endpoint like `invoke(type, method, args)` — unauditable, unreusable
- ❌ Put project-specific logic into `BridgeActions.cs`
- ❌ Claim "it's a network / resource problem" without `frame` evidence
- ❌ Commit recipes containing accounts, passwords, internal addresses or business flows
