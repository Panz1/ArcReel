"""验证参考生视频 script_plan 落盘时，project_update 能把本集新增资产登记进 project.json。

这是 ``unregistered_asset`` 根因修复的④：reference_video 模式此前只把 new_assets 写进 script_plan
文件，从不回写 project.json（drama 模式经 save_script 的 project_update 会回写）。本测试直接覆盖
``write_formal_script_plan_locked`` 的 project_update 接缝，确认：
  1. 成功提交时，project.json 与 script_plan 同事务落盘、资产写入资产表；
  2. project_update 抛错时，project.json 与 script_plan 都按字节回滚，不留半场；
  3. 不传 project_update 时，project.json 不被触碰。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.artifacts import artifact_activation
from lib.script.plan_new_assets import resolve_new_assets
from lib.script.script_review import write_formal_script_plan_locked


@pytest.fixture(autouse=True)
def _neutralize_artifact_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    # 真实项目都经迁移、Artifact Manifest 已激活；本测试用最小 project.json，跳过登记（与本次修复无关）。
    monkeypatch.setattr(artifact_activation, "register_current_artifact_if_provable", lambda project_dir, key: None)
    monkeypatch.setattr(artifact_activation, "register_current_artifact", lambda *a, **k: None)


def _seed_project(proj: Path) -> Path:
    (proj / "scripts").mkdir(parents=True, exist_ok=True)
    project_file = proj / "project.json"
    project_file.write_text(
        json.dumps(
            {"title": "Demo", "characters": {}, "scenes": {}, "props": {}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_file


def _backfilled_new_assets() -> list[dict[str, str]]:
    """模拟 _backfill_new_assets_from_units 产出的 register 项（角色 + 场景）。"""
    return [
        {
            "type": "character",
            "name": "赵磊",
            "decision": "register",
            "reason": "从 unit 说话人位自动补登",
            "description": "",
            "voice_style": "",
        },
        {
            "type": "scene",
            "name": "乡村小酒馆",
            "decision": "register",
            "reason": "从 unit 场景引用自动补登",
            "description": "",
        },
    ]


def test_project_update_registers_new_assets_into_project_json(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    project_file = _seed_project(proj)
    plan_path = proj / "scripts" / "script_plan_reference_units.json"
    content = {"units": [{"text": "@[赵磊]走进@[乡村小酒馆]", "duration": 5}]}

    new_assets = _backfilled_new_assets()
    resolved = resolve_new_assets(json.loads(project_file.read_text(encoding="utf-8")), new_assets)

    changed = write_formal_script_plan_locked(
        proj, 1, plan_path, content, project_update=resolved.apply_to_project
    )

    assert changed is True
    written_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert written_plan == content
    written_project = json.loads(project_file.read_text(encoding="utf-8"))
    assert "赵磊" in written_project["characters"]
    assert "乡村小酒馆" in written_project["scenes"]


def test_project_update_rolls_back_on_failure(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    project_file = _seed_project(proj)
    plan_path = proj / "scripts" / "script_plan_reference_units.json"
    plan_path.write_text(json.dumps({"units": [{"old": True}]}, ensure_ascii=False), encoding="utf-8")
    content = {"units": [{"text": "新规划", "duration": 5}]}

    def boom(project: dict) -> None:
        project.setdefault("characters", {})["张三"] = {"description": "会被回滚"}
        raise RuntimeError("模拟 project_update 失败")

    with pytest.raises(RuntimeError):
        write_formal_script_plan_locked(proj, 1, plan_path, content, project_update=boom)

    # 两者都必须按字节回滚到写前状态
    assert json.loads(plan_path.read_text(encoding="utf-8")) == {"units": [{"old": True}]}
    assert json.loads(project_file.read_text(encoding="utf-8"))["characters"] == {}


def test_without_project_update_leaves_project_json_untouched(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    project_file = _seed_project(proj)
    plan_path = proj / "scripts" / "script_plan_reference_units.json"
    content = {"units": [{"text": "无资产", "duration": 5}]}

    changed = write_formal_script_plan_locked(proj, 1, plan_path, content)

    assert changed is True
    assert json.loads(project_file.read_text(encoding="utf-8"))["characters"] == {}
