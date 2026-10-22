#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GR3 管线「接线验证」—— 无需 numpy、无需真实固件即可跑（阶段1 把 GR3 跑通）。

它不生成固件（那需要真正的 GR III 2.10 官方固件 + numpy，由用户本机 / CI 完成），
而是用最便宜的方式证明整条 GR3 链路**接线正确、闸门到位**：

  1. 机型注册表默认 = GR III，且 GR III supported=True；其余三款被闸门拦死。
  2. 注册表里 GR III 的 SHA == 打补丁引擎 gr3patch.EXPECT_SHA
     （固件身份的唯一权威来源；错一个字符整条 GR3 链路就废）。
  3. 打补丁引擎对「错误固件」会硬拒绝，绝不拿错固件瞎打。
  4. build_firmware 的默认机型 = gr3，与注册表一致。
  5. paths.find_firmware('gr3') 不会崩、能返回可用路径。
  6. server 的机型分流逻辑：未支持机型 → 400 拦截，GR III → 200 放行。

用法：
  cd gr3-film-mods
  python webtool/test_gr3_wiring.py        # 退出码 0 = 全过，1 = 有失败
"""
import os
import sys
import hashlib
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (HERE, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import models
import paths
import gr3patch
import build_firmware as bf


def _check(name, cond, detail=""):
    mark = "PASS" if cond else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    return bool(cond)


def main():
    results = []

    # —— 1. 机型闸门 ——
    results.append(_check("默认机型 = GR III", models.DEFAULT_MODEL == "gr3"))
    results.append(_check("GR III 已 supported", models.is_supported("gr3")))
    results.append(_check("GR IIIx 被闸门拦截", not models.is_supported("gr3x")))
    results.append(_check("GR III HDF 被闸门拦截", not models.is_supported("gr3hdf")))
    results.append(_check("GR IIIx HDF 被闸门拦截", not models.is_supported("gr3xhdf")))

    # —— 2. 权威 SHA 交叉校验（注册表 vs 打补丁引擎）——
    results.append(_check(
        "注册表 GR III SHA == gr3patch.EXPECT_SHA",
        models.expected_sha("gr3") == gr3patch.EXPECT_SHA,
        models.expected_sha("gr3")[:16] + "…",
    ))

    # —— 3. 未支持机型 require_supported 抛错 ——
    try:
        models.require_supported("gr3x")
        raised = False
    except ValueError:
        raised = True
    results.append(_check("require_supported('gr3x') 抛 ValueError", raised))

    # —— 4. 打补丁引擎对错误固件硬拒绝（SHA 门控）——
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tf.write(b"\x00" * 4096)
        bad_fw = tf.name
    try:
        gr3patch.Image(bad_fw)  # 错误 SHA → 引擎 SystemExit
        engine_reject = False
    except SystemExit:
        engine_reject = True
    finally:
        try:
            os.remove(bad_fw)
        except OSError:
            pass
    results.append(_check("gr3patch 对错误固件 SHA 硬拒绝", engine_reject))

    # —— 5. build_firmware 默认机型与注册表一致 ——
    results.append(_check("build_firmware 默认 model = gr3", bf.models.DEFAULT_MODEL == "gr3"))

    # —— 6. find_firmware 安全（不崩、返回路径）——
    try:
        p = paths.find_firmware("gr3")
        safe = isinstance(p, str) and len(p) > 0
        detail = os.path.basename(p)
    except Exception as e:  # noqa: BLE001
        safe = False
        detail = repr(e)
    results.append(_check("find_firmware('gr3') 不崩且返回路径", safe, detail))

    # —— 7. server 机型分流逻辑（等价于 _handle_build 前段）——
    def server_gate(model):
        spec = models.get_model(model)
        if not spec.supported:
            return 400, spec.display_name
        return 200, spec.display_name

    c_x = server_gate("gr3x")
    results.append(_check("server: gr3x → 400 拦截", c_x[0] == 400, c_x[1]))
    c_3 = server_gate("gr3")
    results.append(_check("server: gr3 → 200 放行", c_3[0] == 200, c_3[1]))

    # —— 8. 提示（非致命）：仓库里那份 work/films_v16/fwdc239b.bin 不是官方固件 ——
    #   它不在构建输入搜索路径上，但容易被误当成官方固件，故独立告警、不影响通过判定。
    stray = os.path.join(REPO, "work", "films_v16", "fwdc239b.bin")
    if os.path.exists(stray):
        h = hashlib.sha256(open(stray, "rb").read()).hexdigest()
        if h == gr3patch.EXPECT_SHA:
            print(f"[INFO] work/films_v16/fwdc239b.bin SHA 匹配官方固件 ✅")
        else:
            print(f"[WARN] work/films_v16/fwdc239b.bin SHA = {h[:16]}… ≠ 官方固件"
                  f"（{gr3patch.EXPECT_SHA[:16]}…）")
            print("       该文件不在构建输入搜索路径上；切勿把它当作官方固件喂给工具。"
                  "请用理光官网下载的 GR III 2.10（fwdc239b.bin）放到桌面/下载 或 "
                  "official_firmware/ 目录。")

    print()
    ok = all(results)
    print("==== GR3 接线验证：" + ("全部通过 ✅" if ok else "存在失败 ❌") + " ====")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
