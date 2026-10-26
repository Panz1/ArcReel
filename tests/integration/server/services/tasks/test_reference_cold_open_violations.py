"""参考生视频首集冷开场 unit 的原文锚校验豁免。

冷开场 unit 闪前借用本集源文区间之外的场面（爆点清单取材），没有本集锚可言：
``cold_open=true`` 时跳过 validate_source_text_anchor，普通 unit 的空锚 / 假锚照旧拦截。
"""

from pathlib import Path

from lib.script.reference_video.voice_settings import VoiceRenderSettings
from server.text_generation import ReferenceSplitCaps, collect_reference_flat_violations


def _caps() -> ReferenceSplitCaps:
    return ReferenceSplitCaps(
        default_duration=None,
        durations=[8],
        reference_durations=[8],
        text_durations=[8],
        text_problem=None,
        max_duration=8,
        max_refs=None,
        voice=VoiceRenderSettings(model_id="m", audio_ready=set()),
    )


def _collect(units: list[dict], novel_text: str, tmp_path: Path):
    # 水合判据经产物清单读 project.json，要求项目已到当前 schema；本测试不涉及参考图，
    # 落一个当前版本的空壳项目即可
    (tmp_path / "project.json").write_text('{"schema_version": 18}', encoding="utf-8")
    return collect_reference_flat_violations(
        units,
        {"schema_version": 18},
        project_path=tmp_path,
        episode=1,
        novel_text=novel_text,
        caps=_caps(),
        source_language="zh",
        new_assets=[],
    )


def test_cold_open_unit_skips_anchor_validation(tmp_path: Path):
    """cold_open=true：空锚 / 锚不在本集源文都不拦，正文与档位等其他校验照常生效。"""
    violations = _collect(
        [
            {"duration_seconds": 8, "cold_open": True, "source_text": "这段话不在本集源文里", "text": "闪前画面"},
            {"duration_seconds": 8, "cold_open": True, "source_text": "", "text": "谁能想到，三个月后他们会为钱反目。"},
        ],
        "本集源文。",
        tmp_path,
    )
    assert violations == []


def test_plain_unit_with_empty_anchor_still_rejected(tmp_path: Path):
    """豁免只认 cold_open 标记：普通 unit 空锚 / 假锚仍被 validate_source_text_anchor 拦截。"""
    violations = _collect(
        [
            {"duration_seconds": 8, "source_text": "", "text": "正文"},
            {"duration_seconds": 8, "source_text": "这段话不在本集源文里", "text": "正文"},
        ],
        "本集源文。",
        tmp_path,
    )
    codes = {(violation.code, violation.label) for violation in violations}
    assert ("source_text_empty", "unit E1U01") in codes
    assert ("source_text_not_verbatim", "unit E1U02") in codes
