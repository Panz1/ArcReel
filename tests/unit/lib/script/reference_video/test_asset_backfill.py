"""``asset_backfill`` 的判定边界。

补登是「模型漏列 new_assets」时的最后一道网，判错方向只有两种代价：漏补 → 整批规划被
``unregistered_asset`` 拒收；错补 → 脏资产名进 project.json。这里锁住这两种边界。
"""

from __future__ import annotations

from lib.script.reference_video.asset_backfill import (
    backfill_new_assets_from_units,
    is_clean_asset_name,
    looks_like_place_name,
)


def _by_name(items):
    return {item["name"]: item["type"] for item in items}


class TestTypeInference:
    def test_speaker_position_becomes_character(self):
        units = [{"text": "@[赵磊]{我不想在城里混了}"}]
        result = _by_name(backfill_new_assets_from_units([], units, {}))
        assert result == {"赵磊": "character"}

    def test_place_suffix_becomes_scene(self):
        units = [{"text": "@[乡村小酒馆] 傍晚，灯光昏暗。"}]
        result = _by_name(backfill_new_assets_from_units([], units, {}))
        assert result == {"乡村小酒馆": "scene"}

    def test_non_place_visual_mention_becomes_character(self):
        """不开口的人（只在画面位出现）不能被当成场景派去生成场景参考图。"""
        units = [{"text": "@[苏晚]、@[唐笑笑]、@[夏禾] 站在 @[村口]。"}]
        result = _by_name(backfill_new_assets_from_units([], units, {}))
        assert result == {"苏晚": "character", "唐笑笑": "character", "夏禾": "character", "村口": "scene"}

    def test_type_is_order_independent(self):
        """先出现在画面、后开口的人仍是角色（按 unit 顺序判定会误判成场景）。"""
        units = [{"text": "@[赵磊] 推开门。"}, {"text": "@[赵磊]{我的天！}"}]
        result = _by_name(backfill_new_assets_from_units([], units, {}))
        assert result == {"赵磊": "character"}

    def test_same_unit_speaker_and_visual_stays_character(self):
        units = [{"text": "@[赵磊] 端起酒杯。@[赵磊]{干了！}"}]
        result = _by_name(backfill_new_assets_from_units([], units, {}))
        assert result["赵磊"] == "character"

    def test_looks_like_place_name(self):
        assert looks_like_place_name("林家老院子") is True
        assert looks_like_place_name("村口") is True
        assert looks_like_place_name("赵磊") is False
        assert looks_like_place_name("") is False

    def test_place_suffix_zi(self):
        """院子 / 房子 / 屋子一类以「子」收尾的地点，不能被判成角色。"""
        assert looks_like_place_name("老院子") is True
        assert looks_like_place_name("废弃房子") is True
        units = [{"text": "@[老院子] 杂草齐腰。"}]
        assert _by_name(backfill_new_assets_from_units([], units, {})) == {"老院子": "scene"}


class TestCoverage:
    def test_registered_names_are_not_rebackfilled(self):
        project = {"characters": {"赵磊": {"description": "已登记"}}}
        units = [{"text": "@[赵磊]{走}"}]
        assert backfill_new_assets_from_units([], units, project) == []

    def test_model_entries_are_not_overridden(self):
        model = [{"type": "scene", "name": "乡村小酒馆", "decision": "register", "description": "旧木屋"}]
        units = [{"text": "@[乡村小酒馆] 傍晚。"}]
        result = backfill_new_assets_from_units(model, units, {})
        assert result == model

    def test_empty_units_keep_input_untouched(self):
        model = [{"type": "scene", "name": "村口", "decision": "register"}]
        assert backfill_new_assets_from_units(model, [], {}) == model


class TestMalformedReferences:
    """畸形引用（典型是 ``@[@[X]]`` 双重包裹）不该被固化成资产名。"""

    def test_clean_name_predicate(self):
        assert is_clean_asset_name("唐笑笑") is True
        assert is_clean_asset_name("  ") is False
        assert is_clean_asset_name("@[唐笑笑") is False
        assert is_clean_asset_name("唐]笑笑") is False

    def test_wrapped_reference_is_not_backfilled_as_garbage(self):
        units = [{"text": "@[@[唐笑笑]] 站在两步开外。@[唐笑笑]{来，对着镜头说一句。}"}]
        result = backfill_new_assets_from_units([], units, {})
        names = [item["name"] for item in result]
        assert all("@" not in name and "[" not in name and "]" not in name for name in names), names
        # 说话人位那处仍照常补登为角色
        assert names == ["唐笑笑"]
