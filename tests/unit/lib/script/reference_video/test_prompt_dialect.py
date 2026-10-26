"""提示词方言：模型识别与三段论渲染的逐方言断言。

方言承载所有随模型变化的写法——参考素材指代、绑定句式、主体记号、台词句式、时间码、
音色声明、主体锁定、口型指令、负向承载；除此之外三段论的其余部分（风控尾注、商品高保真
声明）一律不变，故这里只断言会变的那几处。
"""

from __future__ import annotations

import pytest

from lib.script.reference_video.prompt_dialect import (
    GENERIC,
    MINIMAX_H3,
    SEEDANCE,
    WAN30,
    dialect_for,
)
from lib.script.reference_video.prompt_render import render_unit_prompt
from lib.script.reference_video.voice_settings import VoiceRenderSettings
from lib.script.script_models import ReferenceResource

_PROJECT = {"characters": {"张三": {}}, "scenes": {"酒馆": {}}}
_REFS = [
    ReferenceResource(type="character", name="张三"),
    ReferenceResource(type="scene", name="酒馆"),
]
_TEXT = "@[张三] 推开 @[酒馆] 的门，侧身跨过门槛。@[张三]{我来了。}"


def _render(dialect):
    return render_unit_prompt(
        _TEXT,
        _PROJECT,
        _REFS,
        VoiceRenderSettings(model_id="m", audio_ready=set()),
        dialect=dialect,
    ).prompt


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("doubao-seedance-2-5-260628", SEEDANCE),
        ("doubao-seedance-2.5", SEEDANCE),
        ("wan3.0-video", WAN30),
        ("alibaba/wan3.0-video", WAN30),
        ("MiniMax-H3", MINIMAX_H3),
        ("minimax-h3", MINIMAX_H3),
        # legacy Hailuo 没有多参考能力、也不吃 @ImageN 记号，必须留在 generic
        ("MiniMax-Hailuo-2.3", GENERIC),
        ("MiniMax-Hailuo-02", GENERIC),
        ("S2V-01", GENERIC),
        ("agnes-video-2.5-flash", GENERIC),
        ("kling-video-o1", GENERIC),
        ("", GENERIC),
        (None, GENERIC),
    ],
)
def test_dialect_for_recognizes_model_family(model, expected):
    """认得出的按名字族取方言；认不得（含空值）一律回落 generic——猜错比不猜更贵。"""
    assert dialect_for(model) is expected


def test_generic_dialect_keeps_legacy_syntax():
    """方言化之前的写法逐字不变：既有项目的成片与预览不因本模块存在而改变。"""
    prompt = _render(GENERIC)
    assert "<张三>@图片1、<酒馆>@图片2。" in prompt
    assert "<张三>说 {我来了。}" in prompt
    assert "Avoid: 不要BGM" in prompt


def test_seedance_dialect_uses_official_2_5_forms():
    """Seedance 2.5 官方形态：绑定「图片 N 是 X」、裸名主体、台词「台词 (角色): "…"」，
    负向无前缀行、音频 / 字幕类约束按官方 badcase 教训在声明区末再写一遍。"""
    prompt = _render(SEEDANCE)
    assert "图片 1 是 张三、图片 2 是 酒馆。" in prompt
    assert '台词 (张三): "我来了。"' in prompt
    assert "@图片" not in prompt
    assert "<张三>" not in prompt
    # 负向「首尾双写」的首：声明区末的正文句
    assert "不要bgm、不要背景音乐、不要配乐、不要音乐、不要旋律。不要字幕。" in prompt
    # 尾：无前缀的正文式负向清单
    assert "不要BGM、不要背景音乐" in prompt
    assert "Avoid:" not in prompt
    assert "Negative:" not in prompt


def test_wan_dialect_uses_official_bare_name_forms():
    """万相 3.0 官方形态：绑定「图N是X」、裸名主体、台词「X说："…"」、Negative: 前缀。"""
    prompt = _render(WAN30)
    assert "图1是张三、图2是酒馆。" in prompt
    assert '张三说："我来了。"' in prompt
    assert "Negative: 不要BGM" in prompt
    assert "Avoid:" not in prompt
    assert "<张三>" not in prompt


def test_minimax_h3_dialect_uses_at_image_refs_and_quoted_speech():
    """H3 用 ``@ImageN``（官方 API 示例写 reference images 1，前端统一 @Image1）；台词走引号。

    H3 方言维持尖括号主体与 ``Avoid:`` 前缀的存量形态，官方形态的校正另行推进。
    """
    prompt = _render(MINIMAX_H3)
    assert "<张三>@Image1、<酒馆>@Image2。" in prompt
    assert '<张三>说："我来了。"' in prompt
    assert "@图片" not in prompt
    # H3 没有 Negative 字段，负向约束仍作为正文尾注下发
    assert "Avoid: 不要BGM" in prompt


def test_dialect_audio_reference_format():
    """音频号随方言走；图号与音频号是两条独立编号，格式必须各自成形。"""
    assert GENERIC.audio(2) == "@音频2"
    assert SEEDANCE.audio(2) == "音频 2"
    assert WAN30.audio(2) == "音频2"
    assert MINIMAX_H3.audio(2) == "@Audio2"


def test_dialect_subject_and_binding_forms():
    """主体记号与绑定句式按方言分：万相 / Seedance 官方正文全裸名，generic 保留尖括号存量形态。"""
    assert GENERIC.subject("张三") == "<张三>"
    assert WAN30.subject("张三") == "张三"
    assert SEEDANCE.subject("张三") == "张三"
    assert MINIMAX_H3.subject("张三") == "<张三>"

    assert GENERIC.bind("张三", 1) == "<张三>@图片1"
    assert WAN30.bind("张三", 1) == "图1是张三"
    assert SEEDANCE.bind("张三", 1) == "图片 1 是 张三"
    assert MINIMAX_H3.bind("张三", 1) == "<张三>@Image1"


def test_dialect_timecode_format():
    """时间码格式按方言分：万相要「分段N[起-止秒]」，Seedance 2.5 官方明文响应整数秒时间戳
    （2.0 不响应、会忽略秒数按镜头序号理解，不为 2.0 单设方言），其余模型只用镜头序号。
    """
    assert WAN30.timecode(1, 0, 4) == "分段1[0-4秒]："
    assert WAN30.timecode(2, 4, 9) == "分段2[4-9秒]："
    assert SEEDANCE.timecode(1, 0, 4) == "0-4 秒："
    assert SEEDANCE.timecode(2, 4, 9) == "4-9 秒："
    assert MINIMAX_H3.timecode(3, 9, 15) == "镜头3："
    assert GENERIC.timecode(1, 0, 3) == "镜头1："


def test_dialect_subject_lock_prefix():
    """主体锁定回述只在官方有此写法的方言产出：万相「主体锁定：」；Seedance 官方无此概念
    （绑定清单行「图片 N 是 X」已承担同等职责）不产出；generic / MiniMax 维持存量前缀。"""
    assert WAN30.subject_lock_prefix == "主体锁定："
    assert GENERIC.subject_lock_prefix == "主体锁定："
    assert MINIMAX_H3.subject_lock_prefix == "主体锁定："
    assert SEEDANCE.subject_lock_prefix == ""


def test_dialect_lip_sync_tokens():
    """口型指令随方言：万相「口型同步」、Seedance「逐字同步口型」；无官方指令的方言为空。"""
    assert WAN30.lip_sync == "口型同步"
    assert SEEDANCE.lip_sync == "逐字同步口型"
    assert GENERIC.lip_sync == ""
    assert MINIMAX_H3.lip_sync == ""


def test_dialect_voice_line_forms():
    """音色声明主干随方言：Seedance 官方句式需要图号（voice_line_with_image），纯画外退化
    通用主干；其余方言只有通用主干。"""
    assert SEEDANCE.voice_line_with_image == "{image} 使用{audio} 音色，只取音色、语速与情绪，台词以正文为准"
    assert WAN30.voice_line_with_image == ""
    assert GENERIC.voice_line_with_image == ""
    assert "台词音色参考" in WAN30.voice_line


def test_dialect_transition_only_emitted_for_wan():
    """转场指令只有万相 3.0 有官方 token；其余方言回落空串，不把认不牢的指令硬塞进去。"""
    assert WAN30.transition("cut") == "硬切转场"
    assert WAN30.transition("dissolve") == "叠化转场"
    assert SEEDANCE.transition("cut") == ""
    assert MINIMAX_H3.transition("cut") == ""
    assert GENERIC.transition("cut") == ""
