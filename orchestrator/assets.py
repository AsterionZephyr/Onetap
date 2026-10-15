"""orchestrator.assets — 图像库的读取与校验

图像库是**资产**，不是识别策略（CONTEXT.md）。每条资产记录：图像、比例位置、
出生尺寸、用途。出生尺寸用于判定「帧与资产是否同源」（INV-4）：

  实测反例：1372 宽的模板在 1375 宽的帧里匹配成功，但窗口实际只有 1200 宽。
  有出生尺寸即可当场判定不同源并拒绝，而不是等点歪之后才发现。
"""

import json
import os

from .errors import DiscoveryFailure

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGISTRY = os.path.join(HERE, "assets.json")
TEMPLATE_DIR = os.path.join(os.path.dirname(HERE), "templates")


class Asset:
    def __init__(self, key, spec, registry_dir):
        self.key = key
        self.spec = spec
        self.file = spec.get("file")
        self.kind = spec.get("kind")
        self.purpose = spec.get("purpose")
        self.born_size = tuple(spec["born_size"]) if spec.get("born_size") else None
        self.click_relative = tuple(spec.get("click_relative", (0.5, 0.5)))
        self.path = None
        if self.file:
            candidate = os.path.join(registry_dir, self.file)
            if not os.path.isfile(candidate):
                candidate = os.path.join(TEMPLATE_DIR, self.file)
            self.path = candidate if os.path.isfile(candidate) else None

    @property
    def available(self):
        return self.path is not None

    def check_born_size(self, width, height):
        """INV-4：出生尺寸与当前窗口不同源时拒绝使用。

        出生尺寸为 None 表示「实测不受窗口尺寸影响」（如侧栏图标），放行。
        """
        if self.born_size is None:
            return True, "无出生尺寸限制"
        if tuple(self.born_size) == (width, height):
            return True, f"同源 {width}x{height}"
        return False, (f"不同源：资产出生于 {self.born_size[0]}x{self.born_size[1]}，"
                       f"当前窗口 {width}x{height}")

    def load(self):
        from . import match
        if not self.available:
            raise DiscoveryFailure(
                f"资产 {self.key} 的图像文件不存在：{self.spec.get('file')}")
        return match.load_template(self.path)

    def __repr__(self):
        return f"<Asset {self.key} {self.file} born={self.born_size}>"


class Registry:
    def __init__(self, path=DEFAULT_REGISTRY):
        self.path = path
        self.registry_dir = os.path.dirname(os.path.abspath(path))
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.assets = {k: Asset(k, v, self.registry_dir)
                       for k, v in raw.get("assets", {}).items()}

    def __getitem__(self, key):
        if key not in self.assets:
            raise DiscoveryFailure(f"图像库中没有资产：{key}")
        return self.assets[key]

    def get(self, key):
        return self.assets.get(key)

    def report(self):
        """列出图像库状态，供启动时打印。"""
        lines = []
        for key, a in self.assets.items():
            mark = "OK " if a.available else "缺失"
            born = f"{a.born_size[0]}x{a.born_size[1]}" if a.born_size else "无"
            lines.append(f"  [{mark}] {key:16s} {str(a.file):12s} 出生尺寸={born}")
            if not a.available:
                lines.append(f"          {a.spec.get('consequence', '')}")
        return "\n".join(lines)
