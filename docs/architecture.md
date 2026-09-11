# Architecture and protocol

[English](architecture.md) | [简体中文](architecture.zh-CN.md)

## Why file polling

Sockets / HTTP / named pipes were all considered; file polling won because:

| | File polling | Socket / HTTP |
|---|---|---|
| Unity-side dependencies | **None** (`System.IO`) | Listener thread / coroutine, plus port conflicts and firewalls |
| Crash recovery | File locked → retry next poll, naturally idempotent | Reconnect logic, partial packets |
| Observability | Open the file and look; easy to debug | Packet capture |
| Cross-platform | No differences | Per-platform permissions and firewall policies |

The cost is a **0.5-second polling latency** — completely fine for "drive the game into some state".
For millisecond-level interaction (real-time sync, say), this design is the wrong tool.

---

## Two files, one loop

```
<ProjectRoot>/Temp/<prefix>_cmd.json       ← external writes, Unity reads
<ProjectRoot>/Temp/<prefix>_result.json    ← Unity writes, external reads
```

Living in `Temp/` means: Unity's temp directory, **not under version control**, never shipped in a build.

`<prefix>` defaults to `agentbridge` and can be overridden with the `AGENTBRIDGE_PREFIX`
environment variable. Use it to isolate multiple bridges (or multiple agents on one project).

### Command format

```json
{ "action": "probe", "args": { "type": "GameStateManager", "member": "curState" } }
```

### Result format

```json
{
  "ok": true,
  "action": "probe",
  "state": { "value": "GS_CITY" }
}
```

On failure: `{"ok": false, "action": "...", "error": "..."}`.
For an unknown action it also returns an `available` array, so the caller can self-correct.

---

## The Unity-side loop

`AgentBridge` (`[InitializeOnLoad]`) hooks `EditorApplication.update`:

```
called every frame
  ├─ KeepLoopAlive()      while playing, detect a stalled frame loop → auto-refocus
  └─ ≥ 0.5s since last poll?
       ├─ cmd file exists?
       │    ├─ read it → 【delete it first】(prevents double execution)
       │    ├─ parse JSON
       │    ├─ find the [BridgeAction(name)] method by reflection
       │    ├─ build arguments by parameter name (int/float/bool/string)
       │    ├─ Invoke synchronously
       │    └─ write the result file
       └─ otherwise skip
```

**Key points:**

- **Delete the `cmd` file right after reading.** Otherwise one external write executes twice.
- **Synchronous execution.** An action must be something that finishes on the spot.
  Anything spanning frames (waiting for an asset to load, waiting for an animation) can't be an
  action — the caller should poll state repeatedly instead.
- **`_busy` re-entrancy guard.** New commands aren't handled while one is executing.

---

## Action discovery

No registry. Reflect over every `public static` method in the `AgentBridge` namespace and take the
ones carrying `[BridgeAction("name")]`.

Which means:

- **Adding an action = adding a method.** No ceremony.
- Actions can be defined across **multiple files and classes**, as long as they share the namespace.
- Project-specific actions should live in their own file, so generic and project capabilities
  can be managed separately.

---

## Argument binding

Arguments are looked up by **the method's parameter name** in `args` (falling back to a
lower-cased form).

```json
{"action":"foo","args":{"round":5,"seed":42,"hard":true,"label":"x"}}
```

```csharp
public static JObject Foo(int round, int seed = 0, bool hard = false, string label = "")
```

- Supported types: `int` / `float` / `bool` / `string`
- Not provided, has a default → the default is used
- Not provided, no default → the type's zero value (no error)

---

## Relationship to batchmode

They're **mutually exclusive** — Unity won't open the same project twice.

| Editor state | What you can do |
|---|---|
| **Closed** | batchmode: compile checks, EditMode pure-logic tests |
| **Open** | AgentBridge: drive scenes, read runtime state |

Typical rhythm:

```
Read / edit code           (editor state doesn't matter)
   ↓
Close editor → batchmode compile check    ← fast, good while iterating on code
   ↓
Open editor → reproduce with AgentBridge  ← when you need actual scene state
```

---

## Security boundaries

- Scripts live under `Assets/Editor/` → **editor-only compilation, never shipped in a build**
- Command/result files live in `Temp/` → not under version control
- **There is no generic "invoke any method" endpoint.** Every capability must be explicitly
  implemented in an actions file — a deliberate choice: auditable, reusable, reviewable
- `probe` is read-only. It doesn't write and doesn't call methods.
