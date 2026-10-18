
import io, os, sys
R = r"E:\TOOLS\ScriptsGames\Onetap"; sys.path.insert(0, R)
from orchestrator import apps, match, verdict, programs, targets
from orchestrator.steps import step8_run_task as s8
for k in ("ww", "nte", "zmd"):
    m = apps.get(k)
    print(k, "->", m.__name__, m.__file__.split("Onetap")[-1], len(io.open(m.__file__, encoding="utf-8").readlines()), "行")
ww, nte, zmd = apps.get("ww"), apps.get("nte"), apps.get("zmd")
checks = [
    ("match.verify_identity", match.verify_identity is ww.verify_identity),
    ("match.locate_daily_row", match.locate_daily_row is ww.locate_daily_row),
    ("match.nte_locate_start", match.nte_locate_start is nte.nte_locate_start),
    ("match.NTE_CHECK_SIZE", match.NTE_CHECK_SIZE is nte.NTE_CHECK_SIZE),
    ("match.zmd_locate_start", match.zmd_locate_start is zmd.zmd_locate_start),
    ("verdict.ww_verdict", verdict.ww_verdict is ww.ww_verdict),
    ("verdict.nte_verdict", verdict.nte_verdict is nte.nte_verdict),
    ("verdict.NTE_LOGDIR", verdict.NTE_LOGDIR is nte.NTE_LOGDIR),
    ("verdict.ZmdLogWindow", verdict.ZmdLogWindow is zmd.ZmdLogWindow),
    ("s8.navigate_to_tasks", s8.navigate_to_tasks is ww.navigate_to_tasks),
    ("s8.wait_for_nte_completion", s8.wait_for_nte_completion is nte.wait_for_nte_completion),
    ("s8.NTE_SETTLE_SECONDS", s8.NTE_SETTLE_SECONDS is nte.NTE_SETTLE_SECONDS),
    ("s8.WW_SETTLE_SECONDS_missing", not hasattr(ww, "NTE_SETTLE_SECONDS")),
]
bad = [n for n, ok in checks if not ok]
print("shim checks: %d/%d PASS" % (len(checks) - len(bad), len(checks)), "FAIL:", bad)
print("programs.self_check:", programs.self_check())
print("targets.self_check:", targets.self_check())
print("verdict_for zmd/ww/nte 空文本:", [verdict.verdict_for(k, text="")[0] for k in ("zmd","ww","nte")])
print("logdir_self_check:", [ (p, verdict.logdir_self_check(p)) for p in ("ww","nte") ][:1])
