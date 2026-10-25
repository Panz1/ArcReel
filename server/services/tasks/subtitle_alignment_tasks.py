"""字幕句级对齐的生成侧预热（``render`` 车道）。

字幕句级对齐（``lib/speech/subtitle_alignment.py``，docs/adr/0108）的 ASR 成本目前只由
读路径首次物化支付：打开剪辑页时每个单元冷启动一次 Whisper（CPU 几十秒），多单元并发
物化还会争抢 CPU，实测整页字幕要等几分钟。本模块把这次计算提前到「生成落盘时」：旁白
配音（tts）或带音频的视频（video / reference_video）成功并选中为当前版本后，入队一个
``render_subtitle_alignment`` 任务，在 render 车道上走呈现读模型的完整物化——对齐 spans
落 :mod:`lib.speech.alignment_cache` 的磁盘缓存，字幕/呈现 JSON 顺带落盘并登记 manifest，
剪辑页此后即取即用。

开关是部署级环境变量 ``ARCREEL_SUBTITLE_ALIGNMENT``（docs/adr/0108）：字幕计时策略是
技术机制而非创作参数，按部署统一取舍，不看项目。

预热与读取走同一个 ``PresentationReadModelService.materialize_unit``：ADR 0108 的红线
（写入路径与校验路径必须同口径注入对齐策略）由构造保证，不重复实现任何选择逻辑。

预热是尽力而为：判定缺席（开关关、脚本/版本缺席）一律 ``skipped``-成功，物化的预期缺席
（依赖未装、音频读不出、单元不可呈现）与意外异常同样不判失败——缓存 miss 时读路径仍会
现场计算，预热失败没有用户可见后果，不该在任务列表里报警。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lib.artifacts.version_manager import VersionManager
from lib.generation.generation_queue import GenerationQueue
from lib.generation.render_lane import RENDER_MEDIA_TYPE
from lib.jianying_draft.basis import WITH_NARRATION, default_draft_narration, effective_unit_variant
from lib.project.project_manager import ProjectManager, get_project_manager, is_reference_video_project
from lib.script.script_editor import resolve_items
from lib.speech.narration_config import POST_PRODUCTION
from lib.speech.speech_artifact_provenance import RenditionVariant
from lib.speech.speech_composition import SpeechMode, admit_script_unit
from lib.speech.subtitle_alignment import subtitle_alignment_enabled

logger = logging.getLogger(__name__)

#: 字幕对齐预热的任务类型；``render_`` 前缀使其走 render 车道（并发 1、不绑供应商）。
SUBTITLE_ALIGNMENT_TASK_TYPE = "render_subtitle_alignment"


@dataclass(frozen=True, slots=True)
class _PrewarmTarget:
    """预热任务入队决策：要预热的媒体资源类型与判定依据的剧本。"""

    resource_type: str
    script_file: str


@dataclass(frozen=True, slots=True)
class _PrewarmPlan:
    """预热执行器的判定结果：物化一个单元的指定呈现版本。"""

    resource_type: str
    variant: RenditionVariant


async def enqueue_subtitle_alignment_prewarm(
    queue: GenerationQueue,
    *,
    project_name: str,
    task_type: str,
    resource_id: str,
    version: int | None,
    script_file: str | None,
    user_id: str,
) -> None:
    """媒体生成任务成功收尾后的预热入队；尽力而为，任何失败只记日志。

    只在部署开着 ``ARCREEL_SUBTITLE_ALIGNMENT`` 且本次产物确实被选中为当前版本时入队——
    不选中的付费版本（提交时剧本已改）没有可预热的对象。入队条件从宽、执行判定从严：
    执行器会再按脚本与媒体现状重新判定，两次判定之间项目状态可以自由变化。
    """

    try:
        target = await asyncio.to_thread(
            _prewarm_target,
            project_name=project_name,
            task_type=task_type,
            resource_id=resource_id,
            version=version,
            script_file=script_file,
        )
    except Exception:
        logger.warning(
            "字幕对齐预热判定失败 project=%s unit=%s task_type=%s", project_name, resource_id, task_type, exc_info=True
        )
        return
    if target is None:
        return
    try:
        await queue.enqueue_task(
            project_name=project_name,
            task_type=SUBTITLE_ALIGNMENT_TASK_TYPE,
            media_type=RENDER_MEDIA_TYPE,
            resource_type=target.resource_type,
            resource_id=resource_id,
            script_file=target.script_file,
            user_id=user_id,
            source="worker",
        )
    except Exception:
        logger.warning("字幕对齐预热入队失败 project=%s unit=%s", project_name, resource_id, exc_info=True)


def _prewarm_target(
    *,
    project_name: str,
    task_type: str,
    resource_id: str,
    version: int | None,
    script_file: str | None,
) -> _PrewarmTarget | None:
    """入队前的同步判定：部署开关、媒体资源类型与「产物是否为当前版本」。"""

    if not subtitle_alignment_enabled():
        return None
    pm = get_project_manager()
    if task_type == "video":
        resource_type = "videos"
    elif task_type == "reference_video":
        resource_type = "reference_videos"
    elif task_type == "tts":
        resource_type = "reference_videos" if is_reference_video_project(pm.load_project(project_name)) else "videos"
    else:
        return None
    if not script_file or version is None:
        return None
    versions = VersionManager(pm.get_project_path(project_name))
    # 音频对配音对齐、视频对音轨对齐，判的都是各自产物的当前版本；未选中（如提交时剧本
    # 已改）的付费版本没有可预热的对象，读路径也不会用它。
    produced_type = "audio" if task_type == "tts" else resource_type
    if versions.get_current_version(produced_type, resource_id) != version:
        return None
    return _PrewarmTarget(resource_type=resource_type, script_file=script_file)


async def execute_subtitle_alignment_task(task: dict[str, Any], projects: ProjectManager) -> dict[str, Any]:
    """预热一个单元的字幕对齐：走呈现读模型完整物化，ASR 结果落缓存、产物落盘。"""

    project_name = str(task["project_name"])
    resource_id = str(task["resource_id"])
    resource_type = task.get("resource_type")
    script_file = task.get("script_file")

    def _plan() -> _PrewarmPlan | str:
        if not subtitle_alignment_enabled():
            return "alignment_disabled"
        if resource_type not in ("videos", "reference_videos"):
            return f"unsupported_resource_type:{resource_type!r}"
        if not isinstance(script_file, str) or not script_file:
            return "script_file_missing"
        project = projects.load_project(project_name)
        script = projects.load_script_readonly(project_name, script_file)
        items, id_field, kind = resolve_items(script)
        item = next(
            (
                candidate
                for candidate in items
                if isinstance(candidate, Mapping) and str(candidate.get(id_field)) == resource_id
            ),
            None,
        )
        if item is None:
            return "unit_not_in_script"
        admission = admit_script_unit(kind, item)
        if not admission.allowed or admission.mode is None:
            return "unit_not_presentable"
        versions = VersionManager(projects.get_project_path(project_name))
        has_narration_audio = versions.get_current_version("audio", resource_id) > 0
        narration = default_draft_narration(project)
        variant = effective_unit_variant(narration, admission.mode, has_narration_audio=has_narration_audio)
        if (
            variant == POST_PRODUCTION
            and narration == WITH_NARRATION
            and admission.mode is SpeechMode.NARRATOR_VOICEOVER
            and not has_narration_audio
        ):
            # TTS 项目的画外音单元还没等到配音：等 TTS 任务收尾的预热，不对视频音轨白算一遍。
            return "narration_pending"
        return _PrewarmPlan(resource_type=resource_type, variant=variant)

    try:
        plan = await asyncio.to_thread(_plan)
    except Exception:
        logger.warning(
            "字幕对齐预热判定失败 project=%s unit=%s script=%s", project_name, resource_id, script_file, exc_info=True
        )
        return {"status": "skipped", "reason": "plan_failed"}
    if isinstance(plan, str):
        return {"status": "skipped", "reason": plan}

    # 呈现读模型较重（依赖呈现/目录/版本链路），与 render 同类执行器一样执行时才导入。
    from server.services.presentation.presentation_read_model import (
        PresentationReadModelService,
        PresentationUnavailableError,
    )

    try:
        await PresentationReadModelService(projects).materialize_unit(
            project_name=project_name,
            resource_type=plan.resource_type,
            resource_id=resource_id,
            variant=plan.variant,
        )
    except PresentationUnavailableError as exc:
        return {"status": "skipped", "reason": "presentation_unavailable", "detail": str(exc)}
    except Exception:
        logger.warning("字幕对齐预热物化失败 project=%s unit=%s", project_name, resource_id, exc_info=True)
        return {"status": "skipped", "reason": "materialize_failed"}
    return {"status": "aligned", "variant": plan.variant}


__all__ = [
    "SUBTITLE_ALIGNMENT_TASK_TYPE",
    "enqueue_subtitle_alignment_prewarm",
    "execute_subtitle_alignment_task",
]
