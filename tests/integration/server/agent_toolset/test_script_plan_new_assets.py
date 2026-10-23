"""AI 规划脚本带出本集新增资产：上下文带已登记资产，引用须已登记或在本次新增项中。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fakes import use_text_generator
from tests.integration.server.agent_tool_support import (
    ToolHarness,
    drama_project,
    drama_quarantine_path,
    drama_scene,
    drama_script_plan_path,
    nr_generator_returning,
    nr_quarantine_path,
    nr_script_plan_path,
    nr_segment,
    nr_source,
    run_declared_tool,
    run_rv_split,
    rv_quarantine_path,
    rv_script_plan_path,
    rv_source,
    rv_unit,
    said,
    use_fake_caps,
)


def _new(name: str, decision: str, **fields: Any) -> dict[str, Any]:
    return {"type": "character", "name": name, "decision": decision, "reason": "原文第一次出现", **fields}


#: register / derivative 的 description 必须够长到能直接作画（校验会拦「一个称呼」式的短描述），
#: 夹具一律引用这两个常量，避免为了过校验而在每个用例里抄一遍外观。
_TAO_DESC = "十岁女童，梳双丫髻，穿藕荷色短袄与月白长裤，脚踩黑布鞋，眉眼清亮"
_HAWKER_DESC = "四十岁上下的挑担货郎，皮肤黝黑，戴草帽，穿灰蓝粗布短褂，扁担两头挂着竹筐"


def _register_known_cast(fake_ctx: ToolHarness) -> None:
    fake_ctx.pm.project_payload["characters"]["张三"] = {
        "description": "主角，粗布短打",
        "aliases": ["三哥"],
        "derivatives": {"少年": {"description": "十五岁，束发"}},
    }
    (fake_ctx.project_path / "project.json").write_text(
        json.dumps(fake_ctx.pm.project_payload, ensure_ascii=False), encoding="utf-8"
    )


def _drama_generator(content: dict[str, Any]):
    class _Generator:
        async def generate(self, _request, project_name=None):
            class _Result:
                text = json.dumps(content, ensure_ascii=False)

            return _Result()

    async def create(_task_type, project_name=None, **_kwargs):
        return _Generator()

    return create


@pytest.mark.parametrize("route", ["narration", "drama"])
async def test_planning_context_carries_registered_names_aliases_and_descriptions(
    fake_ctx: ToolHarness, video_request_facts, route: str
) -> None:
    if route == "drama":
        drama_project(fake_ctx)
        fake_ctx.pm.project_payload["characters"] = {}
    else:
        nr_source(fake_ctx)
    _register_known_cast(fake_ctx)

    out = await run_declared_tool("generate_script_plan", fake_ctx, {"episode_id": 1, "dry_run": True})

    prompt = said(out)
    assert "三哥" in prompt
    assert "主角，粗布短打" in prompt
    assert "张三/少年" in prompt
    assert "十五岁，束发" in prompt
    assert "new_assets" in prompt


async def test_narration_plan_accepts_references_to_listed_new_assets(
    fake_ctx: ToolHarness, monkeypatch, video_request_facts
) -> None:

    nr_source(fake_ctx)
    new_assets = [
        _new("小桃", "register", description=_TAO_DESC),
        _new("小桃", "register", description="十岁女童，同样的称呼配一段不同的外观描述，用来验证同类同名只留第一项"),
    ]
    segment = nr_segment("E1S01", 4, "张三在村口等人", characters_in_segment=["张三", "小桃"])
    use_text_generator(monkeypatch, nr_generator_returning([segment], new_assets=new_assets))

    out = await run_declared_tool("generate_script_plan", fake_ctx, {"episode_id": 1})

    assert out.problem is None, out
    saved = json.loads(nr_script_plan_path(fake_ctx).read_text(encoding="utf-8"))
    assert [item["description"] for item in saved["new_assets"]] == [_TAO_DESC]


async def test_narration_plan_refuses_an_unlisted_unregistered_reference(
    fake_ctx: ToolHarness, monkeypatch, video_request_facts
) -> None:

    nr_source(fake_ctx)
    segment = nr_segment("E1S01", 4, "张三在村口等人", characters_in_segment=["小桃"])
    use_text_generator(monkeypatch, nr_generator_returning([segment]))

    out = await run_declared_tool("generate_script_plan", fake_ctx, {"episode_id": 1})

    assert out.problem is not None
    codes = [v["code"] for v in json.loads(nr_quarantine_path(fake_ctx).read_text(encoding="utf-8"))["violations"]]
    assert codes == ["unregistered_asset"]


async def test_narration_plan_quarantines_an_unresolvable_decision(
    fake_ctx: ToolHarness, monkeypatch, video_request_facts
) -> None:

    nr_source(fake_ctx)
    segment = nr_segment("E1S01", 4, "张三在村口等人", characters_in_segment=["三叔"])
    new_assets = [_new("三叔", "merge", target="王五")]
    use_text_generator(monkeypatch, nr_generator_returning([segment], new_assets=new_assets))

    out = await run_declared_tool("generate_script_plan", fake_ctx, {"episode_id": 1})

    assert out.problem is not None
    codes = [v["code"] for v in json.loads(nr_quarantine_path(fake_ctx).read_text(encoding="utf-8"))["violations"]]
    assert codes == ["new_asset_target_unresolved"]


async def test_reference_plan_accepts_a_skipped_speaker_and_new_mentions(
    fake_ctx: ToolHarness, monkeypatch, video_request_facts
) -> None:
    rv_source(fake_ctx)
    unit = rv_unit("@[张三] 在 @[村口] 遇见 @[货郎]。\n@[路人]{借过。}")
    new_assets = [_new("货郎", "register", description=_HAWKER_DESC), _new("路人", "skip")]

    out = await run_rv_split(fake_ctx, monkeypatch, [unit], new_assets=new_assets)

    assert out.problem is None, out
    assert not rv_quarantine_path(fake_ctx).exists()
    saved = json.loads(rv_script_plan_path(fake_ctx).read_text(encoding="utf-8"))
    assert [item["name"] for item in saved["new_assets"]] == ["货郎", "路人"]


async def test_reference_plan_backfills_an_unlisted_speaker(fake_ctx: ToolHarness, monkeypatch, video_request_facts) -> None:
    """未列进 new_assets 的说话人由兜底补登为角色，不再整批判收。

    兜底的口径是「引用必须落地」，说话人位同样算引用：``@[路人]{借过。}`` 只要说得上话，
    就该有一项 register 把它接住——判错的代价（事后在资产阶段改类型）远小于一份内容完好的
    产出因为一个纯登记字段缺失而作废。
    """
    rv_source(fake_ctx)

    out = await run_rv_split(fake_ctx, monkeypatch, [rv_unit("@[张三] 在 @[村口] 等人。\n@[路人]{借过。}")])

    assert out.problem is None, out
    assert not rv_quarantine_path(fake_ctx).exists()
    saved = json.loads(rv_script_plan_path(fake_ctx).read_text(encoding="utf-8"))
    assert "路人" in [item["name"] for item in saved["new_assets"]]


@pytest.mark.parametrize(
    ("new_assets", "saved"),
    [([_new("小桃", "register", description=_TAO_DESC)], True), ([], False)],
    ids=["listed", "unlisted"],
)
async def test_drama_plan_references_must_be_registered_or_listed(
    fake_ctx: ToolHarness, monkeypatch, video_request_facts, new_assets: list[dict[str, Any]], saved: bool
) -> None:

    drama_project(fake_ctx)
    use_fake_caps(fake_ctx, supported_durations=(4, 6, 8), default_duration=4)
    scene = drama_scene(
        characters_in_scene=["阿离", "小桃"],
        utterances=[{"kind": "dialogue", "speaker": "小桃", "text": "姐姐回来了。"}],
    )
    content = {"title": "第一集", "scenes": [scene], "new_assets": new_assets}
    use_text_generator(monkeypatch, _drama_generator(content))

    out = await run_declared_tool("generate_script_plan", fake_ctx, {"episode_id": 1})

    assert drama_script_plan_path(fake_ctx).exists() is saved
    if not saved:
        assert out.problem is not None
        codes = [
            v["code"] for v in json.loads(drama_quarantine_path(fake_ctx).read_text(encoding="utf-8"))["violations"]
        ]
        assert codes == ["unregistered_asset"]


async def test_a_quarantined_reference_plan_keeps_its_new_assets(
    fake_ctx: ToolHarness, monkeypatch, video_request_facts
) -> None:
    rv_source(fake_ctx)
    unit = rv_unit("@[张三] 在 @[村口] 遇见 @[货郎] 和 @[王五]。")
    new_assets = [_new("货郎", "register", description=_HAWKER_DESC)]

    out = await run_rv_split(fake_ctx, monkeypatch, [unit], new_assets=new_assets)

    assert out.problem is not None
    draft = json.loads(rv_quarantine_path(fake_ctx).read_text(encoding="utf-8"))
    # 模型列的「货郎」原样保留；「王五」既未登记也没列进 new_assets，兜底补登给它补了一项
    # （空描述，但不参与空描述校验，否则兜底会把自己补的项判成违约而卡死晋升）。
    assert [item["name"] for item in draft["content"]["new_assets"]] == ["货郎", "王五"]
    assert draft["content"]["new_assets"][1]["reason"].startswith("从 unit ")
