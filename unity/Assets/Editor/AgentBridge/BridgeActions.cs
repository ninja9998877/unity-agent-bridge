using System;
using System.Reflection;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AgentBridge
{
    /// <summary>
    /// 【这是 AI agent 实时编辑的文件】
    ///
    /// 每个 [BridgeAction] 方法 = 一条「快捷到达某个现场」的通道。
    /// 遇到要复现的问题时，**先读代码搞清「怎样才能到达那个现场」**，
    /// 然后按那条逻辑在这里加一个**最直达**的 action，编译后即可用指令驱动编辑器到达该场景。
    ///
    /// 【加 action 的规则】详见 docs/adding-actions.md，要点：
    ///   1. public static，返回值建议 JObject（会作为 state 回传）
    ///   2. 参数支持 int / float / bool / string，名字与指令里的 args 键对应
    ///   3. 一步到位：直达场景，**不要模拟人的点击过程**（那是 OS 层该干的事）
    ///   4. 尽量把关键状态放进返回值 —— agent 靠它做断言，比看截图可靠
    ///   5. 涉及随机的场景**务必支持传入随机种子**，否则 bug 复现不出来
    ///   6. 命名建议：动词_对象，如 enter_battle / set_hero_level
    ///
    /// 本文件只放**通用能力**；与具体项目业务相关的 action 请另建文件（同样打 [BridgeAction] 即可被发现），
    /// 这样通用能力可以独立升级、也便于开源。
    /// </summary>
    public static class BridgeActions
    {
        // ─────────────────────────────────────────────────────────────
        // 链路自检
        // ─────────────────────────────────────────────────────────────

        [BridgeAction("ping")]
        public static JObject Ping()
        {
            return new JObject
            {
                ["message"] = "pong",
                ["time"] = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"),
                ["unityVersion"] = Application.unityVersion,
            };
        }

        /// <summary>列出当前已注册的所有 action（agent 上手时先调这个）</summary>
        [BridgeAction("list_actions")]
        public static JObject ListActions()
        {
            var arr = new JArray();
            foreach (var n in AgentBridge.ListActions()) arr.Add(n);
            return new JObject { ["count"] = arr.Count, ["actions"] = arr };
        }

        [BridgeAction("editor_info")]
        public static JObject EditorInfo()
        {
            var scene = EditorSceneManager.GetActiveScene();
            return new JObject
            {
                ["isPlaying"] = EditorApplication.isPlaying,
                ["isPaused"] = EditorApplication.isPaused,
                ["sceneName"] = scene.name,
                ["scenePath"] = scene.path,
                ["sceneDirty"] = scene.isDirty,
                ["projectPath"] = Application.dataPath,
                ["productName"] = Application.productName,
            };
        }

        // ─────────────────────────────────────────────────────────────
        // 编辑器控制
        // ─────────────────────────────────────────────────────────────

        /// <summary>
        /// 进入播放模式，并开启「失焦自动抢焦点」。
        ///
        /// 刻意**不写** ProjectSettings：实测 PlayerSettings.runInBackground 对编辑器播放循环
        /// 无效（设为 true 时 frameCount 依然冻结），却会弄脏受版本控制的 ProjectSettings.asset。
        /// 真正解决问题的是 AutoFocus，见 docs/pitfalls.md。
        /// </summary>
        [BridgeAction("play")]
        public static JObject Play()
        {
            AgentBridge.AutoFocus = true;
            EditorApplication.isPlaying = true;
            AgentBridge.FocusEditorWindow();
            return new JObject
            {
                ["isPlaying"] = true,
                ["autoFocus"] = AgentBridge.AutoFocus,
            };
        }

        [BridgeAction("stop")]
        public static JObject Stop()
        {
            AgentBridge.AutoFocus = false;
            EditorApplication.isPlaying = false;
            return new JObject { ["isPlaying"] = false, ["autoFocus"] = false };
        }

        [BridgeAction("pause")]
        public static JObject Pause(bool paused)
        {
            EditorApplication.isPaused = paused;
            return new JObject { ["isPaused"] = EditorApplication.isPaused };
        }

        /// <summary>
        /// 强制 Unity 刷新资源、触发脚本重编译。
        ///
        /// ⚡ **编辑器失焦时不会自动刷新资源** —— 改完代码不显式调一次，
        /// 编译压根不会启动，随后 `compile_status` 报的"编译通过"就是假的。
        /// 所以 `bridge.py compile` 会先调它再等。
        /// </summary>
        [BridgeAction("refresh")]
        public static JObject Refresh()
        {
            AssetDatabase.Refresh();
            return new JObject
            {
                ["ok"] = true,
                ["isCompiling"] = EditorApplication.isCompiling,
                ["compilationFailed"] = EditorUtility.scriptCompilationFailed,
            };
        }

        /// <summary>
        /// 编译状态。**改完代码要先调它**：
        /// C# 编译失败时 Unity 会继续用**上一次成功的程序集**运行，
        /// 于是所有 action 照常响应 —— 但跑的是旧代码，结果全是假成功。
        /// 这是最隐蔽的一类"查了半天查不出"。
        /// </summary>
        [BridgeAction("compile_status")]
        public static JObject CompileStatus()
        {
            bool failed = EditorUtility.scriptCompilationFailed;
            bool compiling = EditorApplication.isCompiling;
            return new JObject
            {
                ["isCompiling"] = compiling,
                ["compilationFailed"] = failed,
                ["isUpdating"] = EditorApplication.isUpdating,
                // ready = 可以安全驱动
                ["ready"] = !compiling && !failed,
            };
        }

        /// <summary>手动把编辑器窗口拉回前台（播放循环会因失焦停摆）</summary>
        [BridgeAction("focus")]
        public static JObject Focus()
        {
            return new JObject
            {
                ["ok"] = AgentBridge.FocusEditorWindow(),
                ["autoFocus"] = AgentBridge.AutoFocus,
            };
        }

        /// <summary>
        /// 播放循环探针。连发两次比对 frameCount：
        ///   在涨  = 循环在跑（卡住是逻辑问题）
        ///   不涨  = 循环被挂起（编辑器失焦/暂停），此时所有异步系统都不会推进
        /// 排查「看起来卡住了」时，**第一步就应该调这个**。
        /// </summary>
        [BridgeAction("frame")]
        public static JObject Frame()
        {
            return new JObject
            {
                ["isPlaying"] = Application.isPlaying,
                ["frameCount"] = Time.frameCount,
                ["time"] = Math.Round(Time.realtimeSinceStartup, 2),
                ["runInBackground"] = Application.runInBackground,
                ["isFocused"] = Application.isFocused,
                ["editorPaused"] = EditorApplication.isPaused,
                ["editorCompiling"] = EditorApplication.isCompiling,
            };
        }

        // ─────────────────────────────────────────────────────────────
        // 场景
        // ─────────────────────────────────────────────────────────────

        /// <summary>打开指定场景（按 Assets/ 下的相对路径或场景名）</summary>
        [BridgeAction("open_scene")]
        public static JObject OpenScene(string scene)
        {
            string path = scene;
            if (!path.StartsWith("Assets/"))
            {
                var guids = AssetDatabase.FindAssets(scene + " t:Scene");
                if (guids.Length == 0) return Error("找不到场景: " + scene);
                path = AssetDatabase.GUIDToAssetPath(guids[0]);
            }

            var opened = EditorSceneManager.OpenScene(path);
            return new JObject
            {
                ["ok"] = opened.IsValid(),
                ["sceneName"] = opened.name,
                ["scenePath"] = opened.path,
            };
        }

        /// <summary>列出项目里的所有场景（agent 找入口用）</summary>
        [BridgeAction("list_scenes")]
        public static JObject ListScenes()
        {
            var arr = new JArray();
            foreach (var guid in AssetDatabase.FindAssets("t:Scene"))
                arr.Add(AssetDatabase.GUIDToAssetPath(guid));
            return new JObject { ["count"] = arr.Count, ["scenes"] = arr };
        }

        // ─────────────────────────────────────────────────────────────
        // 通用状态读取
        // ─────────────────────────────────────────────────────────────

        /// <summary>
        /// **只读**探针：按类型名读一个静态成员；给了 via 就先读静态成员拿到实例，再读它的成员。
        ///
        /// 覆盖两种最常见的写法：
        ///   probe(type="GameStateManager", member="curState")              // 静态字段/属性
        ///   probe(type="GameStateManager", member="curState", via="Instance") // 单例实例成员
        ///
        /// 只能读，不能写、不能调方法。需要「驱动」就老老实实加一个显式 action —— 那样才可审计、可复用。
        /// </summary>
        [BridgeAction("probe")]
        public static JObject Probe(string type, string member = "", string via = "")
        {
            var t = FindType(type);
            if (t == null) return Error("找不到类型: " + type);
            if (string.IsNullOrEmpty(member)) return Error("member 不能为空");

            object target = null;
            if (!string.IsNullOrEmpty(via))
            {
                target = ReadMember(t, null, via, out var viaErr);
                if (viaErr != null) return Error(viaErr);
                if (target == null) return Error($"静态成员 {type}.{via} 为空，拿不到实例");
            }

            object value = ReadMember(target?.GetType() ?? t, target, member, out var err);
            if (err != null) return Error(err);

            return new JObject
            {
                ["ok"] = true,
                ["type"] = t.FullName,
                ["target"] = target == null ? "static" : target.GetType().FullName,
                ["member"] = member,
                // 显式转 JToken：三元里 string / JValue 没有公共类型
                ["value"] = value == null ? (JToken)JValue.CreateNull() : (JToken)value.ToString(),
                ["valueType"] = value?.GetType().FullName,
            };
        }

        private static object ReadMember(Type type, object target, string name, out string error)
        {
            error = null;
            if (type == null) { error = "类型为空"; return null; }

            const BindingFlags Flags =
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance;

            try
            {
                var prop = type.GetProperty(name, Flags);
                if (prop != null) return prop.GetValue(target);

                var field = type.GetField(name, Flags);
                if (field != null) return field.GetValue(target);
            }
            catch (Exception e)
            {
                error = "读取失败: " + e.Message;
                return null;
            }

            error = $"类型 {type.FullName} 上找不到成员 {name}";
            return null;
        }

        /// <summary>在所有已加载程序集里按名字找类型（支持 "Namespace.Type" 与短名）</summary>
        private static Type FindType(string name)
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                var t = asm.GetType(name, false);
                if (t != null) return t;
            }
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try { types = asm.GetTypes(); }
                catch { continue; }
                foreach (var t in types)
                    if (t.Name == name) return t;
            }
            return null;
        }

        private static JObject Error(string msg) => new JObject { ["ok"] = false, ["error"] = msg };

        // ─────────────────────────────────────────────────────────────
        // 按需生长的区段
        //
        // 下面这些是「遇到具体问题时才加」的位置。示例形态（当前未启用）：
        //
        // /// <summary>直接到达「某场战斗的第 N 回合」</summary>
        // [BridgeAction("enter_battle")]
        // public static JObject EnterBattle(int battleId, int round, int seed = 0)
        // {
        //     // 1. 按项目里真实的入场路径，把游戏送到目标现场
        //     // 2. 传 seed 固定随机（暴击/闪避/随机目标不固定就复现不出来）
        //     // 3. 返回关键状态：回合数 / 双方血量 / buff 列表 ... 供 agent 断言
        // }
        //
        // ─────────────────────────────────────────────────────────────
    }
}
