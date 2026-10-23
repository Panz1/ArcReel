"""从 unit 正文兜底补登本集新增资产。

本模块是「模型漏列 ``new_assets``」时的最后一道网：规划校验按「引用必须已登记」判违约，
而 ``new_assets`` 是模型可省略的输出字段（解析侧可选、请求侧虽已置必填但各 backend 未必真守
schema）。资产表为空的**新项目**里，一旦模型漏列，正文里每个 ``@[名称]`` 都会判成未登记，
整批规划被拒收——一份内容完好的产出因为一个纯登记字段的缺失而作废。

补登只补「登记」，不动正文：给引用名一个 ``register`` 决定，并推断它的资产类型。推理只为让
登记项落在正确的表里；**类型判错的代价远小于整批判收**，故此处一律先补登、再让人在资产阶段修正。

两条路径共用本模块：

- 拆分产出（``server.text_generation.generate_reference_script_plan``）——校验前补登；
- 草稿重校验（``server.draft_workflow``，晋升 / 内容确认前的读时重算）——同一份草稿换个入口
  也要得到同样的判定，否则「生成时能过、晋升时被拒」会变成新的不可解释状态。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from lib.project.asset_types import ASSET_SPECS, asset_name_comparison_key
from lib.script.plan_new_assets import AUTO_BACKFILL_REASON_MARK
from lib.references.reference_catalog import build_reference_catalog
from lib.script.reference_video.text_parser import extract_mentions, speech_speaker_references

#: 兜底补登时判定「这是地点不是人」的地名尾字。
#:
#: 正常路径下类型由模型自己给（``new_assets[].type``），这里只处理模型漏列时的猜测。画面位的
#: ``@[X]`` 本身不区分人与地点：``@[苏晚]、@[唐笑笑]、@[夏禾] 站在村口`` 里三个都是角色，
#: ``@[乡村小酒馆]`` 才是场景——单看引用位置无法区分，曾经「画面位一律按场景」的口径把不开口的
#: 角色登记成了场景资产（还会被派去生成场景参考图）。改为按尾字判：中文地名几乎总以地形 / 建筑 /
#: 区划字收尾，人名极少如此。
#:
#: 单字「子」是例外中最高频的一类：院子 / 房子 / 屋子 / 铺子 / 棚子 全以它收尾，不以它收尾的
#: 人名（李子、孔子一类）在当代都市 / 农村题材里几乎不出现，故仍按地点处理。
_PLACE_NAME_SUFFIXES = frozenset(
    "馆店院村口街路巷桥屋房楼室厅场园城山河湖海林田厂校站港岛谷湾区域镇乡亭廊坝滩岭塔寺庙宫子"
)


def looks_like_place_name(name: str) -> bool:
    """兜底类型判定的地名尾字试探；判不出的一律按角色（人名）处理。"""
    return bool(name) and name.strip()[-1] in _PLACE_NAME_SUFFIXES


#: 资产名里不该出现的语法字符：出现即说明引用本身写坏了。
_REFERENCE_GRAMMAR_CHARS = frozenset("@[]{}")


def is_clean_asset_name(name: str) -> bool:
    """引用名能否当作资产名补登。

    畸形引用（典型是把引用重复包一层写成 ``@[@[唐笑笑]]``）会被解析成残片 ``@[唐笑笑``，
    它既不是「模型漏列的新资产」，也不该变成资产表里的名字——补登它等于把语法错误固化成脏数据，
    还会让随后的 ``malformed_mention`` 报告看不出真正原因。这类名字一律跳过，交回校验报错。
    """
    stripped = name.strip()
    return bool(stripped) and not (_REFERENCE_GRAMMAR_CHARS & set(stripped))


def backfill_new_assets_from_units(
    new_assets: list[dict[str, Any]],
    flat_units: Iterable[object],
    project: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """把正文里出现、却未登记也未列进 ``new_assets`` 的引用补成 ``register`` 项。

    ``flat_units`` 是扁平 unit（含 ``text`` 字段）的序列；``project`` 是落盘项目的只读视图，
    补登项只返回、不写回。模型已显式处理（``register`` / ``merge`` / ``skip``）的名字不覆盖：
    它比这里的猜测更可信。

    说话人位 ``@[X]{台词}`` 判角色；画面位 ``@[X]`` 再按地名尾字分场景 / 角色。判定**跨全部
    unit 先聚合再归属**：任一 unit 里说过话就是角色，避免「先出现在画面、后开口」被按顺序判成
    场景，也避免同 unit 内 ``@[X]`` 与 ``@[X]{台词}`` 并存时判成场景。

    补登项不带 description / voice_style——它们只保证引用合法，资产描述仍由资产阶段或人工补。
    空描述不会因此被判违约：补登项的 ``reason`` 带 :data:`plan_new_assets.AUTO_BACKFILL_REASON_MARK`，
    规划校验据此豁免，兜底才不会把自己补出来的项变成无法晋升的死锁。
    名称按正文原样（只去两端空白）落库，判等键只用于去重，不当资产名写出去。
    """
    covered: set[str] = set()
    catalog = build_reference_catalog(dict(project))
    for asset_type in ASSET_SPECS:
        covered |= {asset_name_comparison_key(name) for name in catalog.reference_names(asset_type)}
    for item in new_assets:
        name = item.get("name")
        if isinstance(name, str) and name:
            covered.add(asset_name_comparison_key(name))

    speaker_names: dict[str, str] = {}
    visual_names: dict[str, str] = {}
    for unit in flat_units:
        if not isinstance(unit, Mapping):
            continue
        text = unit.get("text")
        if not isinstance(text, str) or "@" not in text:
            continue
        for raw in speech_speaker_references(text):
            key = asset_name_comparison_key(raw)
            if key and key not in covered and is_clean_asset_name(raw):
                speaker_names.setdefault(key, raw.strip())
        for raw in extract_mentions(text):
            key = asset_name_comparison_key(raw)
            if key and key not in covered and is_clean_asset_name(raw):
                visual_names.setdefault(key, raw.strip())

    backfill: list[dict[str, Any]] = []
    for name in speaker_names.values():
        backfill.append(
            {
                "type": "character",
                "name": name,
                "decision": "register",
                "reason": f"从 unit 说话人位{AUTO_BACKFILL_REASON_MARK}",
                "description": "",
                "voice_style": "",
            }
        )
    for key, name in visual_names.items():
        if key in speaker_names:
            # 任一 unit 里说过话 → 已按角色登记，不再重复登记成场景。
            continue
        if looks_like_place_name(name):
            backfill.append(
                {
                    "type": "scene",
                    "name": name,
                    "decision": "register",
                    "reason": f"从 unit 画面位{AUTO_BACKFILL_REASON_MARK}（按地名尾字判为场景）",
                    "description": "",
                }
            )
        else:
            backfill.append(
                {
                    "type": "character",
                    "name": name,
                    "decision": "register",
                    "reason": f"从 unit 画面位{AUTO_BACKFILL_REASON_MARK}（未开口，按人名判为角色）",
                    "description": "",
                    "voice_style": "",
                }
            )
    if not backfill:
        return list(new_assets)
    return list(new_assets) + backfill


__all__ = ["backfill_new_assets_from_units", "is_clean_asset_name", "looks_like_place_name"]
