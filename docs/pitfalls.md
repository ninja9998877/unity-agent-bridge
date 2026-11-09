# Pitfalls

[English](pitfalls.md) | [简体中文](pitfalls.zh-CN.md)

Ordered by how much pain they caused. The first one is the most misdiagnosed.

---

## 1. ⚡ Editor loses OS focus → the play loop **stops completely**

### Symptom

The game hangs at some loading step, progress bar at 0%, with no error.
**It looks like a network failure, a failed asset download, or a deadlock.**

### The truth

Once the Unity Editor loses OS focus, **the play loop stops advancing frames entirely** —
not slower, *stopped*.

Measured (Unity 2020.3, Windows):

| | `Time.frameCount` |
|---|---|
| While unfocused, over 115 seconds | **2** (frozen) |
| 6 seconds after refocusing | 203 |
| 6 more seconds | 628 |

### Why the fallout is so severe

Lots of async machinery is driven from `MonoBehaviour.Update()`:

- Asset framework drivers (e.g. YooAsset's `YooAssetsDriver` → `OperationSystem.Update()`)
- Your own coroutine schedulers and timers
- Network callback polling

When the frame loop stops, **all of it stops**. An asset load operation stays "in progress" forever,
so it presents as "stuck on the loading screen" — indistinguishable from a network problem.

**A file-driven agent is unfocused by nature** (whose focus is in the terminal), so it will always hit this.

### Two counter-intuitive facts (both measured)

| You'd assume | Reality |
|---|---|
| `PlayerSettings.runInBackground = true` fixes it | ❌ **has no effect** on the editor play loop |
| `Application.isFocused` tells you whether you have focus | ❌ **still returns `true` while unfocused** |

### The countermeasure

The `play` action handles it: it sets `AutoFocus`, and while playing, if the frame counter hasn't
moved for 2 seconds it calls `SetForegroundWindow` to pull the editor back to the front.
`stop` turns it off, so manually pressing Play is unaffected.

Implementing it yourself on Windows is just:

```csharp
[DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hWnd);
[DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

var h = Process.GetCurrentProcess().MainWindowHandle;
ShowWindow(h, 9);        // SW_RESTORE
SetForegroundWindow(h);
```

### The debugging mantra

> **Something's stuck? Measure whether the loop is alive first. Don't guess "network".**

```bash
python tools/bridge.py send frame      # send again a few seconds later, compare frameCount
```

- Increasing → the loop is fine; it's a real logic problem, go read the log
- Frozen → the loop is suspended, and **everything that looks broken right now is an illusion**

---

## 2. A native modal dialog freezes the whole editor — and the bridge goes silent

If Unity pops a **native modal** (most often **"Save Changes?"** when the scene is dirty), **the
whole editor freezes**. The bridge stops responding entirely — every command just times out.

From the outside this looks exactly like "Unity is stuck" or "the network is slow", so it is easy to
burn a lot of time waiting. It is a separate Win32 `#32770` window, so **look at the screen** — a
screenshot will show it immediately.

**Countermeasure** — the tool ships it:

```bash
python tools/bridge.py unblock
# {"ok":true,"dismissed":1,"clicked":"Don't Save"}
```

It finds those dialogs and clicks the **non-committing** button ("Don't Save" / "No" / "Cancel") —
**never "Save"**, which would write to your project files (scenes, prefabs). `send` also runs this
check automatically when a command times out.

> Windows-only (Win32 `EnumWindows` + `BM_CLICK`).

### Where the dialog actually comes from

Don't assume it's a Unity built-in. **Grep your own project first:**

```bash
grep -rn "DisplayDialog\|SaveCurrentModifiedScenesIfUserWantsTo\|SaveOpenScenes" Assets/
```

Projects commonly add their own "Save Changes?" prompt in a play-mode hook — which then fires on
**every** play, and blocks your automation every time. The fix there is not to remove it (humans
want it) but to give it a skip switch that the driver sets before entering Play mode.

### You cannot clear the scene dirty flag

Tempting idea: just reset `Scene.isDirty` before playing, so the prompt never appears.
**It doesn't exist.** Verified by reflecting over the API on Unity 2020.3:

| | result |
|---|---|
| `Scene.isDirty` | **getter only** — no setter, not even internal |
| `Scene.GetIsDirtyInternal` | static, **non-public**, read only |
| `EditorSceneManager` | `MarkSceneDirty` / `MarkAllScenesDirty` — **setting only** |

So there is no "un-dirty" API; the only ways are saving or reloading the scene. **Prefer a skip
switch over trying to clear the flag** — and probe before you guess:

> **Don't guess at an API's shape from memory. Reflect over it and print the real members.**
> A 20-line probe action changed this from "try things until it compiles" into a definite answer.

**The general rule: if nothing has responded for over a minute, look at the screen** instead of
continuing to wait.

---

## 3. Unity doesn't recompile when you think it does — and on failure it silently runs the **old** assembly

Two related traps, both about your code and the running code being out of sync.

### 2a. No recompilation during Play mode

After editing `BridgeActions.cs`, sending a command while still in Play mode won't see the new
action — Unity doesn't recompile scripts during Play mode.

### 2b. A failed compile keeps the **last good** assembly loaded

This one is far more dangerous. When C# compilation fails, Unity keeps running the **previous
successful** assembly. So:

- every action still responds
- the bridge still looks perfectly healthy
- **but you're driving old code, and every result you get is a false success**

Nothing in the response tells you this. You can spend a long time believing a fix worked when it
was never loaded.

### Countermeasure

Do **not** hand-roll this in each script — the tool ships it:

```bash
python tools/bridge.py compile      # waits for compilation, prints errors, exits non-zero on failure
```

```
编译失败 ✗ —— Unity 仍在用上一次成功的程序集运行，此时驱动得到的是旧代码的结果。
  Assets/Editor/MyActions.cs(578,18): error CS1001: Identifier expected
```

`send` also runs a guard by default: if compilation has failed it **refuses to send** rather than
hand you stale results (`--no-guard` opts out). Underneath, both use the `compile_status` action,
which reports `{isCompiling, compilationFailed, ready}` from `EditorUtility.scriptCompilationFailed`.

For the full recompile cycle:

```bash
python tools/bridge.py send stop
sleep 15                            # let Unity recompile
python tools/bridge.py compile      # PASS/FAIL — don't drive until it passes
python tools/bridge.py send play
```

> **If the compile never starts**, the editor probably never noticed the file change. Bring the
> editor window to the foreground — Unity refreshes assets on focus. (Same root cause as pitfall 1:
> an unfocused editor does less than you'd expect.)

---

## 4. Reading a stale result

If you only write the `cmd` file without clearing the `result` file, and Unity happens to be slow
to respond, you can read the *previous* `result` and believe the command already ran.

**Countermeasure**: `bridge.py` **deletes the result file before every `send`**, then writes the command.
Do the same if you implement this yourself.

---

## 5. Unity reads a half-written command file

While your process is mid-write on the `cmd` file, Unity's poll can read **a partial JSON document**
and fail to parse it.

**Countermeasure**: **atomic writes** — write a temp file, then rename.

```python
with open(path + ".tmp", "w", encoding="utf-8") as f:
    f.write(text)
os.replace(path + ".tmp", path)     # rename within the same filesystem is atomic
```

The Unity side should also never crash on a parse failure — return `{"ok": false, "error": "..."}`.

**It goes both ways**: Unity must write the `result` file atomically too. `File.WriteAllText`
truncates first, so a poller can read an empty or half-written file — you get the occasional
`json.load` failure or a lost result. On the Unity side:

```csharp
string tmp = ResultPath + ".tmp";
File.WriteAllText(tmp, json);
if (File.Exists(ResultPath)) File.Replace(tmp, ResultPath, null);
else File.Move(tmp, ResultPath);
```

---

## 6. The same command running twice

If the `cmd` file isn't deleted after reading, the next poll executes it again — and if that
command was `play` or something that sends a message, the consequences are ugly.

**Countermeasure**: **delete immediately after reading** (which is what `AgentBridge.Update()` does).

---

## 7. The `Temp/` directory may not exist

A project that has never been opened has no `Temp/` yet, so writing the command file fails.

**Countermeasure**: ensure the directory exists before writing. `bridge.py` checks and
fails with a clear message.

---

## 8. Mojibake on the Windows console

Python defaults to GBK output on Windows, turning non-ASCII logs into garbage.

**Countermeasure**:

```python
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
```

(`bridge.py` already does this.)

---

## 9. Where the editor log lives

You'll read it constantly while debugging:

| Platform | Path |
|---|---|
| Windows | `%LOCALAPPDATA%\Unity\Editor\Editor.log` |
| macOS | `~/Library/Logs/Unity/Editor.log` |
| Linux | `~/.config/unity3d/Editor.log` |

```bash
python tools/bridge.py log --tail 100
python tools/bridge.py log --tail 50 --grep "YOUR_TAG"
```

> Note: derivatives such as Tuanjie (团结引擎) use a different log path —
> pass `--path` explicitly.

---

## 10. Batchmode and the editor can't run at the same time

Opening the same project with two Unity instances crashes outright
(`HandleProjectAlreadyOpenInAnotherInstance`), and the error message is long enough
that it's easy to misread as "Unity is broken".

**Countermeasure**: make sure the editor is closed before running batchmode
(compile checks / EditMode tests).

---

## 11. Free-text errors can't be branched on — every failure needs a human to read it

### Symptom

A failure looks like this:

```json
{ "ok": false, "error": "Type not found: LoginManager" }
```

A human understands it. **Code does not.** An agent can only paste the whole
sentence into a model and guess, or regex-match it — which breaks the moment
the wording changes.

Worse, the same blob hides who is responsible:

| Failure | What you should do |
|---|---|
| Unity isn't running | Start Unity — retrying is pointless |
| Compilation failed | Fix the compile errors — driving the bridge only yields the *old* assembly |
| Panel not open | Call `open_panel` first — an ordering problem |
| Type name is wrong | Fix the action argument — a code problem |

Four different remedies, indistinguishable from the text.

### Countermeasure: three-segment error codes

| Segment | Meaning | Produced by |
|---|---|---|
| `ZB-CLI-0xx` | Command line: bad arguments/environment, nothing was sent | Python side |
| `ZB-BRIDGE-0xx` | Bridge link: sent but no reply (timeout / compile guard / modal dialog) | Python side |
| `ZB-ACT-0xx` | Action: Unity received and ran it, but it failed | **Classified** from C# text |

```bash
python tools/bridge.py explain              # list every code
python tools/bridge.py explain ZB-ACT-001   # title + what to do
```

A failed `send` now prints the code and the remedy:

```
[bridge] [ZB-BRIDGE-001] Unity is not responding (timeout): timed out, no result
  -> 1) check for a native dialog (bridge.py unblock) 2) send frame ...
```

The JSON result carries it too:

```json
{ "ok": false, "code": "ZB-ACT-001", "error": "Type not found: XXX" }
```

### ⚠️ The ACT segment is *classified*, not authoritative

The C# side still returns free text; `classify_error()` maps it by keyword. So:

- **Only the category is guaranteed**; trust `message` for specifics.
- **Unrecognised text returns `None`** rather than a guessed code — a wrong code
  is worse than no code, because callers branch on it.
- When new wording shows up in logs, add a line to `_ACT_RULES`. **No recompile.**

Making the ACT segment authoritative requires returning codes from C# — that's
the next step, not this one.

### Also: merging `state.ok` into `ok`

`annotate()` turns `ok=true + state.ok=false` into `ok=false` with a code.
Same principle as “a successful call is not a successful execution”.

---

## 12. Two senders on one prefix → reading someone else's result

The bridge is "write a command file → poll for a result file". Two agents sharing a
`--prefix`, or a late result from a request that already timed out, can be mistaken
for your own. Observed symptom: you send `ping` and get back a different action's data.

**Countermeasure (built into `bridge.py`)**:

1. Every command carries a **monotonic `seq`**; Unity echoes it back. `bridge.py`
   matches on `seq` — two consecutive `open_panel` calls no longer cross-wire.
2. If an older Unity bridge doesn't echo `seq`, matching falls back to the `action`
   name, and results **with no `action` field are discarded** rather than trusted.
3. The result file is deleted before every `send`.

`seq` is a plain counter, not a clock — Windows timestamp resolution is poor and
system time can jump backwards, so clocks make bad request IDs.

**Still recommended**: give each agent / session its own `--prefix`
(`--prefix a1`, `--prefix b2`) to keep them apart at the source.
