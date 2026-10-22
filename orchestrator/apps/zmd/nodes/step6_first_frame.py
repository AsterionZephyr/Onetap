"""MaaEnd 的节点 6：先点掉「更新完成」弹窗，再用绿色开始按钮验身份。

两件程序专属的事，都以钩子交给 steps/common/step6_first_frame.py 的骨架：

    pre_frame  自我更新重启后会弹「更新完成」模态框。它在场时底部「开始任务」
               被遮罩压暗（实测白占比 0.171 -> 0.000），身份校验必然失败 ——
               那不是窗口有问题，是**有个按钮等着点**。双证据才点（应用日志
               「检测到刚更新完成」+ 帧里 ack 形态绿块）；只有标记没有按钮
               ⇒ 立即判「弹窗已不在」，不在骨架里空等。
               必须在身份校验**之前**：身份锚点正是被压暗的那个按钮。

    identity   为什么不用 ☰ 或侧栏模板：MaaEnd 是 Tauri 界面，既没有 ok-ww 的
               侧栏、也没有 ok-nte 的青色侧条，templates/ 里也没有它的图。
               改用**本程序独有的元素**：底部控制条的绿色开始按钮。它在 MaaEnd
               所有页面上都在场，而别的程序几乎不可能同时满足「底部 15% 带 +
               这个尺寸 + 这个长宽比 + 高白占比」。于是它同时是
                   身份证据 —— 帧里有它 ⇒ 这帧几乎必然是 MaaEnd
                   定位结果 —— 下一步要点的就是它
               两者**不可能不一致**（同一次匹配），省掉一次重复匹配，也省掉
               「身份通过但定位失败」这种自相矛盾的状态。窗口被全屏游戏盖住时，
               按钮必然不在帧里，同样会被拦住 —— 那正是最该在节点 6 拦住的事。
"""

from .... import match
from ....steps import context
from ....steps.common import step6_first_frame as common

from .. import zmd_update_dismiss


def extra_args(ap):
    # `--no-update-gate` 由共用实现提供（它同时管 pre_frame 与身份校验前的闸门），
    # 这里只要不重复添加即可 —— 重复会直接 ArgumentError。
    common.extra_args(ap)


def pre_frame(state, args, log):
    """处理自我更新留下的「更新完成」模态框；返回 None 表示可以抓帧了。"""
    upd = zmd_update_dismiss(state, log=log)
    state.set("update_dismiss", upd)
    if upd["state"] == "failed":
        log(f"  [!!] 更新完成弹窗处理失败：{upd.get('why', '?')}")
        return ("failed", {"update_dismiss": upd},
                f"更新完成弹窗未处理：{upd.get('why', '?')[:120]}")
    return None


def identity(rgb, registry, log):
    """身份校验：底部那个绿色「开始任务」必须在场。"""
    info = match.zmd_locate_start(rgb, log=log)
    btn = info["button"]
    log(f"    [OK] 底部绿色「开始任务」在场 box={tuple(btn['box'])} "
        f"（INV-12：确认这帧真的来自 MaaEnd）")
    return {"score": 1.0, "pos": tuple(btn["center"])}


def body(args, state, log):
    prog = context.resolve_program(state, args, log=log)
    return common.run(state, args, log, prog, identity=identity,
                      pre_frame=pre_frame,
                      identity_hint="（多半是被全屏游戏盖住了 —— 抓帧抓到的是游戏的像素）")


if __name__ == "__main__":
    raise SystemExit(context.run_step("6", "first_frame", body, extra_args,
                                      chain_key="zmd"))
