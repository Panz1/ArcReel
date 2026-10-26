"""爆点清单（overview.hook_points）的存储过滤与模板槽位投影。"""

from lib.project.project_manager import HookPoint, filter_hook_points, hook_points_slot

_SOURCE = "第一章 她当众撕了婚书，转身离去。\n第二章 平淡叙述。"


def _point(**overrides) -> HookPoint:
    entry = {
        "description": "当众撕婚书",
        "kind": "contrast",
        "anchor": "她当众撕了婚书，转身离去。",
        "characters": ["她"],
    }
    entry.update(overrides)
    return HookPoint(**entry)


class TestFilterHookPoints:
    def test_keeps_entries_whose_anchor_hits_source(self):
        kept = filter_hook_points([_point(), _point(description="假爆点", anchor="原文里没有这句话")], _SOURCE)
        assert [point["description"] for point in kept] == ["当众撕婚书"]

    def test_tolerates_whitespace_differences(self):
        # 与参考生视频原文锚同一口径：判定只认字，换行 / 空格不计
        kept = filter_hook_points([_point(anchor="她当众撕了婚书，\n转身离去。")], _SOURCE)
        assert len(kept) == 1

    def test_drops_non_model_entries_and_non_list_input(self):
        assert filter_hook_points(None, _SOURCE) == []
        assert filter_hook_points("bad", _SOURCE) == []
        # 输入约定是 ProjectOverview 解析后的模型列表；裸字典不在此处放行
        assert (
            filter_hook_points([{"description": "裸字典", "kind": "conflict", "anchor": "她当众撕了婚书"}], _SOURCE)
            == []
        )


class TestHookPointsSlot:
    def test_projects_index_kind_label_and_drops_bad_entries(self):
        slot = hook_points_slot(
            [
                {"kind": "conflict", "description": "撕婚书", "anchor": "她当众撕了婚书", "characters": ["她", 3]},
                {"kind": "unknown-kind", "description": "未知类型", "anchor": "平淡叙述。"},
                {"kind": "conflict", "description": "", "anchor": "x"},
                "junk",
            ]
        )
        assert slot[0] == {
            "index": 1,
            "kind": "直接冲突",
            "description": "撕婚书",
            "anchor": "她当众撕了婚书",
            "characters": ["她"],
        }
        assert slot[1]["index"] == 2 and slot[1]["kind"] == "关键场面"
        assert len(slot) == 2

    def test_none_for_missing_empty_or_all_bad(self):
        assert hook_points_slot(None) is None
        assert hook_points_slot([]) is None
        assert hook_points_slot([{"description": "", "anchor": ""}]) is None
