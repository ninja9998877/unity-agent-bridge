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

## 2. Unity doesn't recompile when you think it does — and on failure it silently runs the **old** assembly

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

## 3. Reading a stale result

If you only write the `cmd` file without clearing the `result` file, and Unity happens to be slow
to respond, you can read the *previous* `result` and believe the command already ran.

**Countermeasure**: `bridge.py` **deletes the result file before every `send`**, then writes the command.
Do the same if you implement this yourself.

---

## 4. Unity reads a half-written command file

While your process is mid-write on the `cmd` file, Unity's poll can read **a partial JSON document**
and fail to parse it.

**Countermeasure**: **atomic writes** — write a temp file, then rename.

```python
with open(path + ".tmp", "w", encoding="utf-8") as f:
    f.write(text)
os.replace(path + ".tmp", path)     # rename within the same filesystem is atomic
```

The Unity side should also never crash on a parse failure — return `{"ok": false, "error": "..."}`.

---

## 5. The same command running twice

If the `cmd` file isn't deleted after reading, the next poll executes it again — and if that
command was `play` or something that sends a message, the consequences are ugly.

**Countermeasure**: **delete immediately after reading** (which is what `AgentBridge.Update()` does).

---

## 6. The `Temp/` directory may not exist

A project that has never been opened has no `Temp/` yet, so writing the command file fails.

**Countermeasure**: ensure the directory exists before writing. `bridge.py` checks and
fails with a clear message.

---

## 7. Mojibake on the Windows console

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

## 8. Where the editor log lives

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

## 9. Batchmode and the editor can't run at the same time

Opening the same project with two Unity instances crashes outright
(`HandleProjectAlreadyOpenInAnotherInstance`), and the error message is long enough
that it's easy to misread as "Unity is broken".

**Countermeasure**: make sure the editor is closed before running batchmode
(compile checks / EditMode tests).
