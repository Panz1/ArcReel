"""字幕对齐预热任务的判定与执行语义。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import tests.fakes as fakes
from lib.speech.narration_config import USE_TTS
from lib.speech.subtitle_alignment import SUBTITLE_ALIGNMENT_ENV
from server.services.presentation.presentation_read_model import (
    PresentationReadModelService,
    PresentationUnavailableError,
)
from server.services.tasks import generation_tasks, subtitle_alignment_tasks
from server.services.tasks.render_tasks import RENDER_TASK_EXECUTORS
from server.services.tasks.subtitle_alignment_tasks import (
    SUBTITLE_ALIGNMENT_TASK_TYPE,
    enqueue_subtitle_alignment_prewarm,
    execute_subtitle_alignment_task,
)


class _StubProjects:
    """执行器所需的 ProjectManager 切面：项目字典 + 只读剧本 + 项目目录。"""

    def __init__(self, project: dict[str, Any], script: dict[str, Any], project_path: Path) -> None:
        self._project = project
        self._script = script
        self._project_path = project_path

    def load_project(self, project_name: str) -> dict[str, Any]:
        return self._project

    def get_project_path(self, project_name: str) -> Path:
        return self._project_path

    def load_script_readonly(self, project_name: str, script_file: str) -> dict[str, Any]:
        return self._script


class _StubVersions:
    """VersionManager 切面：只回答当前版本号。"""

    def __init__(self, current: dict[tuple[str, str], int]) -> None:
        self._current = current

    def get_current_version(self, resource_type: str, resource_id: str) -> int:
        return self._current.get((resource_type, resource_id), 0)


class _StubQueue:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def enqueue_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"task_id": "t1", "deduped": False}


def _scene(unit_id: str = "E1S1", **fields: Any) -> dict[str, Any]:
    return {"scene_id": unit_id, **fields}


def _stub_pm(monkeypatch: pytest.MonkeyPatch, project: dict[str, Any], project_path: Path) -> None:
    monkeypatch.setattr(
        subtitle_alignment_tasks,
        "get_project_manager",
        lambda: _StubProjects(project, {}, project_path),
    )


def _stub_versions(monkeypatch: pytest.MonkeyPatch, current: dict[tuple[str, str], int]) -> None:
    monkeypatch.setattr(subtitle_alignment_tasks, "VersionManager", lambda _path: _StubVersions(current))


@pytest.fixture(autouse=True)
def _deployment_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认部署开关关；要打开的用例自行 monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")。"""
    monkeypatch.delenv(SUBTITLE_ALIGNMENT_ENV, raising=False)


# ---------------------------------------------------------------------------
# 入队判定
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prewarm_not_enqueued_when_switch_off(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    project_path = Path(str(tmp_path))
    _stub_pm(monkeypatch, {}, project_path)  # 项目内容不再参与开关判定
    queue = _StubQueue()

    await enqueue_subtitle_alignment_prewarm(
        queue,
        project_name="demo",
        task_type="tts",
        resource_id="E1S1",
        version=1,
        script_file="scripts/episode_1.json",
        user_id="u1",
    )

    assert queue.calls == []


@pytest.mark.asyncio
async def test_prewarm_enqueued_for_selected_tts_audio(monkeypatch: pytest.MonkeyPatch):
    _stub_pm(monkeypatch, {}, Path("/proj"))
    _stub_versions(monkeypatch, {("audio", "E1S1"): 3})
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    queue = _StubQueue()

    await enqueue_subtitle_alignment_prewarm(
        queue,
        project_name="demo",
        task_type="tts",
        resource_id="E1S1",
        version=3,
        script_file="scripts/episode_1.json",
        user_id="u1",
    )

    assert len(queue.calls) == 1
    call = queue.calls[0]
    assert call["task_type"] == SUBTITLE_ALIGNMENT_TASK_TYPE
    assert call["media_type"] == "render"
    assert call["resource_type"] == "videos"  # 非参考视频项目的画外音单元在 videos 上
    assert call["resource_id"] == "E1S1"
    assert call["script_file"] == "scripts/episode_1.json"
    assert call["user_id"] == "u1"
    assert call["source"] == "worker"


@pytest.mark.asyncio
async def test_prewarm_resolves_reference_route_for_tts(monkeypatch: pytest.MonkeyPatch):
    _stub_pm(
        monkeypatch,
        {"generation_mode": "reference_video"},
        Path("/proj"),
    )
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    _stub_versions(monkeypatch, {("audio", "E1S1"): 1})
    queue = _StubQueue()

    await enqueue_subtitle_alignment_prewarm(
        queue,
        project_name="demo",
        task_type="tts",
        resource_id="E1S1",
        version=1,
        script_file="scripts/episode_1.json",
        user_id="u1",
    )

    assert queue.calls[0]["resource_type"] == "reference_videos"


@pytest.mark.asyncio
async def test_prewarm_skipped_when_version_not_selected(monkeypatch: pytest.MonkeyPatch):
    _stub_pm(monkeypatch, {}, Path("/proj"))
    _stub_versions(monkeypatch, {("audio", "E1S1"): 2})
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    queue = _StubQueue()

    await enqueue_subtitle_alignment_prewarm(
        queue,
        project_name="demo",
        task_type="tts",
        resource_id="E1S1",
        version=3,  # 提交时剧本已改，本版未选中为当前
        script_file="scripts/episode_1.json",
        user_id="u1",
    )

    assert queue.calls == []


@pytest.mark.asyncio
async def test_prewarm_skipped_without_script_file(monkeypatch: pytest.MonkeyPatch):
    _stub_pm(monkeypatch, {}, Path("/proj"))
    _stub_versions(monkeypatch, {("audio", "E1S1"): 1})
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    queue = _StubQueue()

    await enqueue_subtitle_alignment_prewarm(
        queue,
        project_name="demo",
        task_type="tts",
        resource_id="E1S1",
        version=1,
        script_file=None,
        user_id="u1",
    )

    assert queue.calls == []


@pytest.mark.asyncio
async def test_prewarm_swallows_enqueue_failure(monkeypatch: pytest.MonkeyPatch):
    """入队失败不外抛：预热是尽力而为，任务行写不进也不影响生成任务的成功语义。"""
    _stub_pm(monkeypatch, {}, Path("/proj"))
    _stub_versions(monkeypatch, {("videos", "E1S1"): 1})
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    queue = _StubQueue()
    queue.error = RuntimeError("queue down")

    await enqueue_subtitle_alignment_prewarm(
        queue,
        project_name="demo",
        task_type="video",
        resource_id="E1S1",
        version=1,
        script_file="scripts/episode_1.json",
        user_id="u1",
    )

    # 尝试过恰好一次入队，失败后不重试、不外抛
    assert len(queue.calls) == 1
    assert queue.calls[0]["task_type"] == SUBTITLE_ALIGNMENT_TASK_TYPE


# ---------------------------------------------------------------------------
# 执行器
# ---------------------------------------------------------------------------


def _stub_materialize(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _fake(self: Any, **kwargs: Any) -> object:
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(PresentationReadModelService, "materialize_unit", _fake)
    return calls


@pytest.mark.asyncio
async def test_executor_skips_when_switch_off(monkeypatch: pytest.MonkeyPatch):
    """部署开关默认关：执行器直接跳过，不读项目。"""
    calls = _stub_materialize(monkeypatch)
    projects = _StubProjects({}, {}, Path("/proj"))

    result = await execute_subtitle_alignment_task(
        {"project_name": "demo", "resource_id": "E1S1", "resource_type": "videos", "script_file": "s.json"},
        projects,
    )

    assert result == {"status": "skipped", "reason": "alignment_disabled"}
    assert calls == []


@pytest.mark.asyncio
async def test_executor_skips_when_unit_not_in_script(monkeypatch: pytest.MonkeyPatch):
    calls = _stub_materialize(monkeypatch)
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    projects = _StubProjects(
        {},
        {"scenes": [_scene("E1S2", voiceover=["旁白"])]},
        Path("/proj"),
    )

    result = await execute_subtitle_alignment_task(
        {"project_name": "demo", "resource_id": "E1S1", "resource_type": "videos", "script_file": "s.json"},
        projects,
    )

    assert result == {"status": "skipped", "reason": "unit_not_in_script"}
    assert calls == []


@pytest.mark.asyncio
async def test_executor_skips_narrator_unit_without_narration_audio(monkeypatch: pytest.MonkeyPatch):
    """TTS 项目的画外音单元还没等到配音：等 TTS 任务收尾的预热，不对视频音轨白算。"""
    calls = _stub_materialize(monkeypatch)
    _stub_versions(monkeypatch, {})  # 无旁白配音
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    projects = _StubProjects(
        {"narration_delivery": USE_TTS},
        {"scenes": [_scene("E1S1", voiceover=["旁白"])]},
        Path("/proj"),
    )

    result = await execute_subtitle_alignment_task(
        {"project_name": "demo", "resource_id": "E1S1", "resource_type": "videos", "script_file": "s.json"},
        projects,
    )

    assert result == {"status": "skipped", "reason": "narration_pending"}
    assert calls == []


@pytest.mark.asyncio
async def test_executor_materializes_use_tts_with_narration_audio(monkeypatch: pytest.MonkeyPatch):
    calls = _stub_materialize(monkeypatch)
    _stub_versions(monkeypatch, {("audio", "E1S1"): 2})
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    projects = _StubProjects(
        {"narration_delivery": USE_TTS},
        {"scenes": [_scene("E1S1", voiceover=["旁白"])]},
        Path("/proj"),
    )

    result = await execute_subtitle_alignment_task(
        {"project_name": "demo", "resource_id": "E1S1", "resource_type": "videos", "script_file": "s.json"},
        projects,
    )

    assert result == {"status": "aligned", "variant": "use_tts"}
    assert calls == [
        {
            "project_name": "demo",
            "resource_type": "videos",
            "resource_id": "E1S1",
            "variant": "use_tts",
        }
    ]


@pytest.mark.asyncio
async def test_executor_skips_when_presentation_unavailable(monkeypatch: pytest.MonkeyPatch):
    async def _unavailable(self: Any, **kwargs: Any) -> object:
        raise PresentationUnavailableError("narration audio lacks typed presentation provenance")

    monkeypatch.setattr(PresentationReadModelService, "materialize_unit", _unavailable)
    _stub_versions(monkeypatch, {("audio", "E1S1"): 2})
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    projects = _StubProjects(
        {"narration_delivery": USE_TTS},
        {"scenes": [_scene("E1S1", voiceover=["旁白"])]},
        Path("/proj"),
    )

    result = await execute_subtitle_alignment_task(
        {"project_name": "demo", "resource_id": "E1S1", "resource_type": "videos", "script_file": "s.json"},
        projects,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "presentation_unavailable"


# ---------------------------------------------------------------------------
# 分派与生成任务挂钩
# ---------------------------------------------------------------------------


def test_executor_registered_in_render_dispatch():
    assert RENDER_TASK_EXECUTORS[SUBTITLE_ALIGNMENT_TASK_TYPE] is execute_subtitle_alignment_task


@pytest.mark.asyncio
async def test_generation_task_success_enqueues_prewarm(monkeypatch: pytest.MonkeyPatch):
    """tts/video/reference_video 任务成功收尾后按任务行的版本与剧本发出预热。"""
    enqueued: list[dict[str, Any]] = []

    async def _fake_prewarm(queue: object, **kwargs: Any) -> None:
        enqueued.append(kwargs)

    async def _fake_tts(project_name: str, resource_id: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"version": 3, "resource_type": "audio", "resource_id": resource_id}

    monkeypatch.setattr(generation_tasks, "enqueue_subtitle_alignment_prewarm", _fake_prewarm)
    fakes.use_generation_success_emit(monkeypatch)
    monkeypatch.setattr(generation_tasks, "get_generation_queue", lambda: object())
    monkeypatch.setitem(generation_tasks._TASK_EXECUTORS, "tts", _fake_tts)

    await generation_tasks.execute_generation_task(
        {
            "task_id": "tts-1",
            "task_type": "tts",
            "project_name": "demo",
            "resource_id": "E1S1",
            "payload": {},
            "script_file": "scripts/episode_1.json",
            "user_id": "u1",
        }
    )

    assert enqueued == [
        {
            "project_name": "demo",
            "task_type": "tts",
            "resource_id": "E1S1",
            "version": 3,
            "script_file": "scripts/episode_1.json",
            "user_id": "u1",
        }
    ]


@pytest.mark.asyncio
async def test_generation_task_other_types_do_not_enqueue_prewarm(monkeypatch: pytest.MonkeyPatch):
    enqueued: list[dict[str, Any]] = []

    async def _fake_prewarm(queue: object, **kwargs: Any) -> None:
        enqueued.append(kwargs)

    async def _fake_image(
        project_name: str, resource_id: str, payload: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        return {"version": 1}

    monkeypatch.setattr(generation_tasks, "enqueue_subtitle_alignment_prewarm", _fake_prewarm)
    fakes.use_generation_success_emit(monkeypatch)
    monkeypatch.setattr(generation_tasks, "get_generation_queue", lambda: object())
    monkeypatch.setitem(generation_tasks._TASK_EXECUTORS, "image", _fake_image)

    await generation_tasks.execute_generation_task(
        {
            "task_id": "img-1",
            "task_type": "image",
            "project_name": "demo",
            "resource_id": "char-1",
            "payload": {},
            "user_id": "u1",
        }
    )

    assert enqueued == []
