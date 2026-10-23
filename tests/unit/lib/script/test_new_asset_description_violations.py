"""新增资产的空描述必须是可报告的违约，而不是静默落进项目资产表。

模型曾把 ``voice_style`` 逐条写满、把 ``description`` 全写成 ``""``：schema 里两者都是带空默认值
的字符串，差别只在提示词字段清单有没有点名。空描述一旦放过，登记出来的资产没有出图依据，
等到生成资产图才暴露。这组用例钉住「空 / 过短即违约」这条判定。
"""

from __future__ import annotations

from typing import Any

from lib.script.plan_new_assets import new_asset_violations

#: 够长的合规描述，用来把断言聚焦在 description 而非其他字段上。
_GOOD = "二十五岁上下的男性，体格壮实，短发凌乱，深色圆领旧 T 恤配洗旧牛仔裤，习惯大幅挥手"

#: 只带一个已登记角色的项目：merge / derivative 要有可归入的本体，否则会先报归并错误。
_PROJECT = {"characters": {"赵磊": {"description": _GOOD}}}


def _item(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "character",
        "name": "赵磊",
        "decision": "register",
        "reason": "主角，有台词",
        "description": _GOOD,
        "aliases": [],
        "target": "",
        "asset_name": "",
        "voice_style": "略带沙哑的青年男声，语速中等偏快",
    }
    return {**base, **fields}


def _codes(items: object, project: dict[str, Any] | None = None) -> list[str]:
    return [violation.code for violation in new_asset_violations(project or {}, items)]


def test_a_blank_registration_description_is_a_violation() -> None:
    assert _codes([_item(description="")]) == ["blank_asset_description"]


def test_an_omitted_registration_description_is_a_violation() -> None:
    item = _item()
    del item["description"]

    assert _codes([item]) == ["blank_asset_description"]


def test_a_whitespace_only_description_is_a_violation() -> None:
    assert _codes([_item(description="   \n ")]) == ["blank_asset_description"]


def test_a_description_shorter_than_a_sentence_is_a_violation() -> None:
    """「壮汉」「玉佩」这类只是把称呼换个说法，出图仍无依据。"""
    assert _codes([_item(type="prop", name="酒杯", description="玻璃杯")]) == ["blank_asset_description"]


def test_a_blank_derivative_description_is_a_violation() -> None:
    item = _item(name="小赵磊", decision="derivative", target="赵磊", asset_name="少年赵磊", description="")

    assert _codes([item], _PROJECT) == ["blank_asset_description"]


def test_a_merge_or_skip_item_may_leave_description_empty() -> None:
    """归并与不登记都不落资产表，本来就没有外观要求。"""
    items = [
        _item(decision="merge", target="赵磊", description=""),
        _item(decision="skip", name="路人甲", type="character", description=""),
    ]

    assert _codes(items, _PROJECT) == []


def test_a_complete_registration_passes() -> None:
    assert _codes([_item()]) == []


def test_every_blank_item_is_reported_not_just_the_first() -> None:
    """一次列全：报告不能停在第一个坏项上，否则每修一条就要再跑一轮。"""
    items = [
        _item(description=""),
        _item(name="陈屿", description=_GOOD),
        _item(type="scene", name="村口", description=""),
    ]

    assert _codes(items) == ["blank_asset_description", "blank_asset_description"]


def test_the_violation_points_at_the_item_name_and_index() -> None:
    violations = new_asset_violations({}, [_item(description="")])

    assert violations[0].label == "new_assets[0]"
    assert "赵磊" in str(violations[0])
    assert "register" in str(violations[0])


def test_a_non_list_payload_is_not_a_description_problem() -> None:
    """new_assets 形状本身由 schema 兜底，这里只判描述，不重复报形状错。"""
    assert _codes(None) == []


def test_an_auto_backfilled_item_is_exempt_from_the_description_rule() -> None:
    """兜底补登的项是系统为「引用合法」自动造的，模型从未给过外观依据。

    若不豁免，兜底会把自己补的项判成违约，整集卡在永远无法晋升的状态——那正是上一轮加兜底
    要避免的死锁。模型的漏列改由提示词的必填约束治理。
    """
    item = _item(name="王五", description="", reason="从 unit 画面位自动补登（未开口，按人名判为角色）")

    assert _codes([item]) == []


def test_a_blank_item_alongside_an_auto_backfilled_one_reports_only_the_blank_one() -> None:
    items = [
        _item(name="王五", description="", reason="从 unit 画面位自动补登（未开口，按人名判为角色）"),
        _item(name="货郎", description=""),
    ]

    violations = new_asset_violations({}, items)

    assert [violation.label for violation in violations] == ["new_assets[1]"]
