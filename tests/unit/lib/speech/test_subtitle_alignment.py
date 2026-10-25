"""字幕句级对齐与 AlignedSubtitleTiming 的单元测试。

对齐引擎依赖可选的 faster-whisper，真实推理不在单测里跑（单独做音频验证）；
这里覆盖纯函数（匹配算法）与策略行为（直接喂对齐结果、回退路径）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from lib.artifacts.artifact_manifest import ArtifactBasis, ArtifactBasisDescriptor
from lib.speech import subtitle_alignment as alignment_module
from lib.speech.alignment_cache import (
    CACHE_SCHEMA,
    cache_key,
    load_cached_spans,
    reset_memory_cache,
    store_cached_spans,
)
from lib.speech.narration_delivery import USE_TTS
from lib.speech.speech_artifact_provenance import SelectedMediaEvidence, SubtitleUtteranceEvidence
from lib.speech.speech_composition import (
    SpeechFieldLocation,
    SpeechMode,
    SpeechOwner,
    SpeechPreparation,
    SpeechUtterance,
)
from lib.speech.speech_presentation import PresentationMedia, SubtitleCue, materialize_speech_presentation
from lib.speech.subtitle_alignment import (
    SUBTITLE_ALIGNMENT_ENV,
    AlignedSubtitleTiming,
    AlignmentSpan,
    AlignmentUnavailable,
    _AlignmentModel,
    _distribute_with_anchors,
    _StreamChar,
    _word_char_stream,
    align_sentences,
    align_sentences_cached,
    alignment_source_media,
    build_aligned_timing,
    match_sentences_to_stream,
    subtitle_alignment_enabled,
    whisper_language_for,
)


def _basis(kind: str, value: str) -> ArtifactBasisDescriptor:
    return ArtifactBasisDescriptor.from_basis(ArtifactBasis.build(kind, kind_version=1, inputs={"value": value}))


def _media(
    path: str,
    *,
    kind: str,
    duration: float,
    version: int = 1,
) -> PresentationMedia:
    digest_char = "a" if kind == "v" else "b"
    return PresentationMedia(
        artifact_path=path,
        version=version,
        selection="current",
        currency="current",
        evidence=SelectedMediaEvidence(
            basis=_basis(kind, str(version)),
            content_digest=f"sha256-v1:{digest_char * 64}",
            actual_duration_seconds=duration,
        ),
    )


def _speech(mode: SpeechMode, *utterances: tuple[str | None, str]) -> SpeechPreparation:
    owner = SpeechOwner.CHARACTER if mode is SpeechMode.CHARACTER_SPEECH else SpeechOwner.NARRATOR
    return SpeechPreparation(
        unit_id="E1U01",
        mode=mode,
        utterances=tuple(
            SpeechUtterance(
                owner=owner,
                speaker=speaker,
                text=text,
                location=SpeechFieldLocation(("utterances", index, "text")),
            )
            for index, (speaker, text) in enumerate(utterances)
        ),
    )


def _utterance(text: str) -> SubtitleUtteranceEvidence:
    return SubtitleUtteranceEvidence(owner=SpeechOwner.NARRATOR, text=text)


def _stream(pairs: Sequence[tuple[str, float, float]]) -> tuple[_StreamChar, ...]:
    return _word_char_stream(pairs)


def test_matches_chinese_sentences_character_by_character() -> None:
    # ASR 把中文按词组分块返回（标点附着在词上），匹配要按字走。
    stream = _stream(
        [
            ("今天，天气", 0.5, 2.0),
            ("很好，我们", 2.0, 3.5),
            ("出发吧。", 3.5, 5.0),
        ]
    )
    spans = match_sentences_to_stream(["今天天气很好。", "我们出发吧。"], stream)

    # 第一句跳过词流里没有的「天气」2 字；两句的首尾字符时间即句子起止。
    assert spans == (
        AlignmentSpan(start_us=500_000, end_us=3_500_000),
        AlignmentSpan(start_us=2_000_000, end_us=5_000_000),
    )


def test_matches_latin_words_and_is_case_insensitive() -> None:
    stream = _stream([("Hello", 1.0, 1.5), ("world,", 1.5, 2.0), ("bye", 2.0, 2.4)])
    spans = match_sentences_to_stream(["HELLO world", "bye"], stream)

    assert spans == (
        AlignmentSpan(start_us=1_000_000, end_us=2_000_000),
        AlignmentSpan(start_us=2_000_000, end_us=2_400_000),
    )


def test_skips_unmatched_chars_within_tolerance_but_fails_past_it() -> None:
    stream = _stream([("嗯那个", 0.0, 1.0), ("走吧", 1.0, 2.0)])
    assert match_sentences_to_stream(["走吧"], stream) == (AlignmentSpan(1_000_000, 2_000_000),)

    noisy = _stream([("嗯啊呃呃呃呃呃呃呃", 0.0, 1.0), ("走吧", 1.0, 2.0)])
    assert match_sentences_to_stream(["走吧"], noisy) == (None,)


def test_consecutive_misheard_tail_chars_still_match() -> None:
    # ASR 把句尾「又哭穷」听成「有苦求」：三个连续替换，编辑成本 3，在长句预算内。
    # 旧版双预算贪心在这里会失败（听错字既不算漏识别、跳过词流又超预算）。
    stream = _stream(
        [
            ("你还好意思说", 0.0, 1.0),
            ("上个月刚发奖金", 1.0, 2.0),
            ("你拉着我们吃了三顿烧烤", 2.0, 3.0),
            ("现在", 3.0, 3.5),
            ("有苦求", 3.5, 4.0),
            ("那我高兴一下不行啊", 4.0, 6.0),
        ]
    )
    spans = match_sentences_to_stream(
        ["你还好意思说上个月刚发奖金你拉着我们吃了三顿烧烤现在又哭穷", "那我高兴一下不行啊"], stream
    )

    assert spans[0] == AlignmentSpan(0, 4_000_000)
    assert spans[1] == AlignmentSpan(4_000_000, 6_000_000)


def test_tolerates_a_misheard_character_via_substitution() -> None:
    # ASR 把「浸」听成「净」：一个替换，其余字符精确对上，句子照常匹配。
    stream = _stream([("夜色像墨一样", 1.0, 2.0), ("净透了", 2.0, 3.0), ("整座城市。", 3.0, 4.0)])
    spans = match_sentences_to_stream(["夜色像墨一样浸透了整座城市。"], stream)

    assert spans == (AlignmentSpan(1_000_000, 4_000_000),)


def test_homophone_cluster_matches_via_substitution() -> None:
    # 「他」被听成「她」（同音）：两个替换 + 两个精确匹配，过半字符真实对上 → 判匹配。
    # 旧版双预算贪心在这里失败（听错字既不算漏识别、跳过词流又超预算）。
    stream = _stream([("她她站着", 0.0, 1.0)])
    assert match_sentences_to_stream(["他他站着"], stream) == (AlignmentSpan(0, 1_000_000),)


def test_match_floor_rejects_substitution_only_alignment() -> None:
    # 连续听错导致过半字符靠替换顶上：编辑成本虽在预算内，但真实对上不足一半 → 判失败。
    stream = _stream([("她她坐着坐着", 0.0, 1.0)])
    assert match_sentences_to_stream(["他他站着站着"], stream) == (None,)


def test_arabic_digits_match_chinese_numerals() -> None:
    # ASR 的逆文本正则化把「二零二三年」输出成「2023年」：数词规范化后两侧都是数字。
    stream = _stream([("在", 0.0, 0.5), ("2023年", 0.5, 2.0), ("的秋天。", 2.0, 3.0)])
    spans = match_sentences_to_stream(["在二零二三年的秋天。"], stream)

    assert spans == (AlignmentSpan(0, 3_000_000),)


def test_vietnamese_diacritics_and_cross_language_numerals_fold() -> None:
    # Whisper 越南语输出：变音符听错（phủ→phụ、kín→kính），数词跨语种错识（một→一）。
    # 规范化折叠变音符 + 数词翻数字后都能对上。
    stream = _stream(
        [
            ("Màn đêm", 0.0, 1.0),
            ("buông xuống", 1.0, 2.0),
            ("như mực", 2.0, 3.0),
            ("phụ kính", 3.0, 4.0),
            ("cả thành phố.", 4.0, 5.0),
        ]
    )
    spans = match_sentences_to_stream(["Màn đêm buông xuống như mực phủ kín cả thành phố."], stream)

    assert spans == (AlignmentSpan(0, 5_000_000),)

    numeral_stream = _stream([("Châm", 0.0, 0.5), ("一", 0.5, 1.0), ("điếu thuốc.", 1.0, 2.0)])
    assert match_sentences_to_stream(["Châm một điếu thuốc."], numeral_stream) == (AlignmentSpan(0, 2_000_000),)


def test_repeated_sentences_consume_the_stream_in_order() -> None:
    stream = _stream([("好。", 0.0, 1.0), ("走。", 1.0, 2.0), ("好。", 2.0, 3.0)])
    spans = match_sentences_to_stream(["好。", "好。"], stream)

    # 两条相同的句子各消耗各自的一段：游标只前进，第二条不会回头抢第一条的位置。
    assert spans == (
        AlignmentSpan(0, 1_000_000),
        AlignmentSpan(2_000_000, 3_000_000),
    )


def test_matching_takes_the_earliest_occurrence_after_the_cursor() -> None:
    stream = _stream([("好。", 0.0, 1.0), ("好的。", 1.0, 2.0)])
    spans = match_sentences_to_stream(["好。", "好的。"], stream)

    assert spans == (
        AlignmentSpan(0, 1_000_000),
        AlignmentSpan(1_000_000, 2_000_000),
    )


def test_punctuation_only_sentence_never_matches() -> None:
    stream = _stream([("……", 0.0, 1.0)])
    assert match_sentences_to_stream(["……"], stream) == (None,)


def test_anchor_spans_are_used_verbatim_and_leading_silence_stays_silent() -> None:
    utterances = (_utterance("第一句。"), _utterance("第二句。"))
    spans = (AlignmentSpan(800_000, 2_000_000), AlignmentSpan(2_500_000, 4_000_000))

    cues = _distribute_with_anchors(utterances, spans, boundary_microseconds=6_000_000)

    # 0~0.8s 是没人声的引导静音：字幕就是不出，这正是对齐相对机械分配的意义。
    assert [(cue.start_microseconds, cue.duration_microseconds) for cue in cues] == [
        (800_000, 1_200_000),
        (2_500_000, 1_500_000),
    ]


def test_unmatched_sentences_fill_the_gap_between_anchors_by_reading_units() -> None:
    utterances = (_utterance("短。"), _utterance("长一点的句子。"), _utterance("锚点句。"))
    spans = (None, None, AlignmentSpan(4_000_000, 6_000_000))

    cues = _distribute_with_anchors(utterances, spans, boundary_microseconds=6_000_000)

    # 前两句阅读单位 2:7，分 [0, 4s)；第三句用实测锚点。
    assert [(cue.start_microseconds, cue.duration_microseconds) for cue in cues] == [
        (0, 888_888),
        (888_888, 3_111_111),
        (4_000_000, 2_000_000),
    ]


def test_all_unmatched_falls_back_to_mechanical() -> None:
    utterances = (_utterance("甲。"), _utterance("乙乙乙！"))

    cues = _distribute_with_anchors(utterances, (None, None), boundary_microseconds=6_000_000)

    assert [(cue.start_microseconds, cue.duration_microseconds) for cue in cues] == [
        (0, 2_000_000),
        (2_000_000, 4_000_000),
    ]


def test_out_of_order_span_cannot_be_placed_and_falls_back_to_mechanical() -> None:
    utterances = (_utterance("第一句。"), _utterance("第二句。"), _utterance("第三句。"))
    # 第三条锚点倒挂在第二条之内：钳位后补不出正时长，整段回退机械分配保底。
    spans = (
        AlignmentSpan(0, 1_000_000),
        AlignmentSpan(2_000_000, 9_000_000),
        AlignmentSpan(1_500_000, 2_500_000),
    )

    cues = _distribute_with_anchors(utterances, spans, boundary_microseconds=5_000_000)

    # 整段回退机械分配：三条阅读单位相同，均分 5s。
    assert [(cue.start_microseconds, cue.duration_microseconds) for cue in cues] == [
        (0, 1_666_666),
        (1_666_666, 1_666_667),
        (3_333_333, 1_666_667),
    ]


def test_missing_audio_or_dependency_falls_back_silently_and_keeps_the_basis_hook() -> None:
    preparation = _speech(SpeechMode.NARRATOR_VOICEOVER, (None, "旁白"))
    video = _media("versions/videos/E1U01_v1.mp4", kind="v", duration=8.0)
    audio = _media("versions/audio/E1U01_v1.wav", kind="a", duration=6.0)

    mechanical = materialize_speech_presentation(
        preparation, variant=USE_TTS, video=video, narration_audio=audio, provider_audio_enabled=True
    )
    aligned = materialize_speech_presentation(
        preparation,
        variant=USE_TTS,
        video=video,
        narration_audio=audio,
        provider_audio_enabled=True,
        timing=AlignedSubtitleTiming(audio_path=Path("versions/audio/E1U01_v1.wav")),
    )

    # 音频文件不在场：策略静默回退，cue 与机械版一致；但依据不同，产物会按新策略重算。
    assert [(cue.start_microseconds, cue.duration_microseconds) for cue in aligned.subtitles] == [
        (cue.start_microseconds, cue.duration_microseconds) for cue in mechanical.subtitles
    ]
    assert aligned.subtitle_basis != mechanical.subtitle_basis


def test_align_sentences_rejects_missing_audio_with_alignment_unavailable() -> None:
    with pytest.raises(AlignmentUnavailable):
        align_sentences(Path("no-such-narration.wav"), ["甲。"])


def test_basis_identity_is_stable_and_names_the_policy() -> None:
    policy = AlignedSubtitleTiming(audio_path=Path("narration.wav"), language="zh", model_size="base")

    assert policy.basis_identity == {
        "kind": "aligned-sentence-forced-alignment",
        "version": 1,
        "model": "base",
        "language": "zh",
    }
    assert (
        policy.basis_identity
        == AlignedSubtitleTiming(audio_path=Path("other.wav"), language="zh", model_size="base").basis_identity
    )
    assert AlignedSubtitleTiming(audio_path=Path("narration.wav")).basis_identity["language"] == "auto"


def test_cues_are_projected_in_presentation_shape() -> None:
    utterances = (_utterance("第一句。"),)
    cues = _distribute_with_anchors(utterances, (AlignmentSpan(500_000, 1_500_000),), boundary_microseconds=6_000_000)

    assert isinstance(cues[0], SubtitleCue)
    assert cues[0].owner is SpeechOwner.NARRATOR
    assert cues[0].text == "第一句。"


# ---------- 语种映射与项目开关 ----------


def test_whisper_language_for_maps_codes_and_legacy_labels() -> None:
    assert whisper_language_for("zh") == "zh"
    assert whisper_language_for("en") == "en"
    assert whisper_language_for("vi") == "vi"
    # 存量项目存过「中文」这类标签（tool_runtime 白名单只允许 zh/en/vi，老数据有标签）。
    assert whisper_language_for("中文") == "zh"
    assert whisper_language_for("English") == "en"
    assert whisper_language_for("vietnamese") == "vi"
    # 缺失或不认识 → None，交给 ASR 自动判别。
    assert whisper_language_for(None) is None
    assert whisper_language_for("") is None
    assert whisper_language_for("fr") is None
    assert whisper_language_for(42) is None


def test_subtitle_alignment_enabled_defaults_off_and_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SUBTITLE_ALIGNMENT_ENV, raising=False)
    # 缺省关：字幕计时策略是部署级机制，未设置的部署保持机械分配。
    assert subtitle_alignment_enabled() is False

    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    assert subtitle_alignment_enabled() is True
    # 非 1/true/yes/on 的值一律关。
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "false")
    assert subtitle_alignment_enabled() is False


# ---------- 预计算 spans 注入 ----------


def test_precomputed_spans_are_used_directly_without_touching_asr() -> None:
    # 音频路径不存在：若走现场对齐会 AlignmentUnavailable 回退机械；预计算注入后直接用。
    policy = AlignedSubtitleTiming(
        audio_path=Path("no-such-narration.wav"),
        precomputed_spans=(AlignmentSpan(1_000_000, 2_500_000), AlignmentSpan(3_000_000, 4_000_000)),
    )
    utterances = (_utterance("第一句。"), _utterance("第二句。"))

    cues = policy.distribute(utterances, boundary_microseconds=5_000_000)

    assert [(cue.start_microseconds, cue.duration_microseconds) for cue in cues] == [
        (1_000_000, 1_500_000),
        (3_000_000, 1_000_000),
    ]


def test_precomputed_spans_with_wrong_length_fall_back_to_live_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Sequence[str]] = []

    def _fake_align(
        audio_path: Path,
        sentences: Sequence[str],
        *,
        language: str | None = None,
        model_size: str = "small",
    ) -> tuple[AlignmentSpan | None, ...]:
        calls.append(tuple(sentences))
        return (None, None)

    monkeypatch.setattr(alignment_module, "align_sentences", _fake_align)
    policy = AlignedSubtitleTiming(
        audio_path=Path("narration.wav"),
        precomputed_spans=(AlignmentSpan(1_000_000, 2_000_000),),
    )

    cues = policy.distribute((_utterance("第一句。"), _utterance("第二句。")), boundary_microseconds=5_000_000)

    # 数量不符：忽略预计算值改跑现场对齐；现场两句都没锚上 → 阅读单位相同，均分 5s。
    assert [list(call) for call in calls] == [["第一句。", "第二句。"]]
    assert [(cue.start_microseconds, cue.duration_microseconds) for cue in cues] == [
        (0, 2_500_000),
        (2_500_000, 2_500_000),
    ]


# ---------- spans 缓存 ----------


@pytest.fixture(autouse=True)
def _reset_alignment_memory_cache() -> Generator[None, None, None]:
    reset_memory_cache()
    yield
    reset_memory_cache()


def test_cache_key_is_stable_and_sensitive_to_every_input() -> None:
    sentences = ["第一句。", "第二句。"]
    # 值类型宽为 Any 才能整包 ** 解包进不同字段组合的 cache_key；运行时各值类型与签名一致。
    base: dict[str, Any] = {
        "model_size": "small",
        "language": "zh",
        "audio_content_digest": "sha256-v1:" + "a" * 64,
        "sentences": sentences,
    }

    assert cache_key(**base) == cache_key(**base)
    assert cache_key(**base) != cache_key(**{**base, "language": "en"})
    assert cache_key(**base) != cache_key(**{**base, "model_size": "base"})
    assert cache_key(**base) != cache_key(**{**base, "audio_content_digest": "sha256-v1:" + "b" * 64})
    assert cache_key(**base) != cache_key(**{**base, "sentences": ["第一句。", "别的一句。"]})


def test_cache_roundtrip_corruption_and_schema_mismatch(tmp_path: Path) -> None:
    key = "k" * 64
    spans = ((1_000_000, 2_000_000), None, (3_000_000, 3_500_000))

    assert load_cached_spans(tmp_path, key) is None
    store_cached_spans(tmp_path, key, spans)
    assert load_cached_spans(tmp_path, key) == spans

    # 损坏 JSON：记日志后按未命中处理。
    path = tmp_path / ".arcreel-cache" / "subtitle-alignment" / f"{key}.json"
    path.write_text("{not json", encoding="utf-8")
    reset_memory_cache()
    assert load_cached_spans(tmp_path, key) is None

    # schema 不符（旧版本键算法）：按未命中处理。
    path.write_text('{"schema": 999, "spans": []}', encoding="utf-8")
    reset_memory_cache()
    assert load_cached_spans(tmp_path, key) is None

    # spans 结构不对：按未命中处理。
    path.write_text(f'{{"schema": {CACHE_SCHEMA}, "spans": [[1]]}}', encoding="utf-8")
    reset_memory_cache()
    assert load_cached_spans(tmp_path, key) is None


def test_align_sentences_cached_miss_runs_alignment_and_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Sequence[str]] = []

    def _fake_align(
        audio_path: Path,
        sentences: Sequence[str],
        *,
        language: str | None = None,
        model_size: str = "small",
    ) -> tuple[AlignmentSpan | None, ...]:
        calls.append(tuple(sentences))
        return (AlignmentSpan(1_000_000, 2_000_000), None)

    monkeypatch.setattr(alignment_module, "align_sentences", _fake_align)
    sentences = ["第一句。", "第二句。"]

    spans = align_sentences_cached(
        Path("narration.wav"),
        sentences,
        language="zh",
        audio_content_digest="sha256-v1:" + "a" * 64,
        cache_dir=tmp_path,
    )

    assert spans == (AlignmentSpan(1_000_000, 2_000_000), None)
    assert [list(call) for call in calls] == [sentences]
    # 落盘后二次调用命中缓存，不再跑 ASR。
    reset_memory_cache()
    spans_again = align_sentences_cached(
        Path("narration.wav"),
        sentences,
        language="zh",
        audio_content_digest="sha256-v1:" + "a" * 64,
        cache_dir=tmp_path,
    )
    assert spans_again == spans
    assert len(calls) == 1


def test_align_sentences_cached_does_not_store_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _unavailable(*args: object, **kwargs: object) -> tuple[AlignmentSpan | None, ...]:
        raise AlignmentUnavailable("faster-whisper is not installed")

    monkeypatch.setattr(alignment_module, "align_sentences", _unavailable)

    with pytest.raises(AlignmentUnavailable):
        align_sentences_cached(
            Path("narration.wav"),
            ["第一句。"],
            language="zh",
            audio_content_digest="sha256-v1:" + "a" * 64,
            cache_dir=tmp_path,
        )
    # 能力缺席不写缓存：下次依赖就绪后重试能恢复。
    key = cache_key(
        model_size="small", language="zh", audio_content_digest="sha256-v1:" + "a" * 64, sentences=["第一句。"]
    )
    assert load_cached_spans(tmp_path, key) is None


# ---------- build_aligned_timing 共用接线 ----------


def _project(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {"source_language": "zh"}
    base.update(fields)
    return base


def test_build_aligned_timing_returns_none_when_deployment_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SUBTITLE_ALIGNMENT_ENV, raising=False)
    preparation = _speech(SpeechMode.NARRATOR_VOICEOVER, (None, "第一句。"))

    assert (
        build_aligned_timing(
            project=_project(),
            audio_path=Path("narration.wav"),
            audio_content_digest="sha256-v1:" + "a" * 64,
            preparation=preparation,
            cache_dir=Path("."),
        )
        is None
    )


def test_build_aligned_timing_injects_precomputed_spans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_align(
        audio_path: Path,
        sentences: Sequence[str],
        *,
        language: str | None = None,
        model_size: str = "small",
    ) -> tuple[AlignmentSpan | None, ...]:
        assert list(sentences) == ["第一句。", "第二句。"]
        return (AlignmentSpan(1_000_000, 2_000_000), AlignmentSpan(2_500_000, 4_000_000))

    monkeypatch.setattr(alignment_module, "align_sentences", _fake_align)
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    preparation = _speech(SpeechMode.NARRATOR_VOICEOVER, (None, "第一句。第二句。"))

    timing = build_aligned_timing(
        project=_project(),
        audio_path=Path("narration.wav"),
        audio_content_digest="sha256-v1:" + "a" * 64,
        preparation=preparation,
        cache_dir=tmp_path,
    )

    assert timing is not None
    assert timing.language == "zh"
    assert timing.precomputed_spans == (
        AlignmentSpan(1_000_000, 2_000_000),
        AlignmentSpan(2_500_000, 4_000_000),
    )


def test_build_aligned_timing_none_when_alignment_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _unavailable(*args: object, **kwargs: object) -> tuple[AlignmentSpan | None, ...]:
        raise AlignmentUnavailable("faster-whisper is not installed")

    monkeypatch.setattr(alignment_module, "align_sentences", _unavailable)
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    preparation = _speech(SpeechMode.NARRATOR_VOICEOVER, (None, "第一句。"))

    assert (
        build_aligned_timing(
            project=_project(),
            audio_path=Path("narration.wav"),
            audio_content_digest="sha256-v1:" + "a" * 64,
            preparation=preparation,
            cache_dir=tmp_path,
        )
        is None
    )


def test_build_aligned_timing_projects_utterances_with_the_prepared_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def _fake_align(
        audio_path: Path,
        sentences: Sequence[str],
        *,
        language: str | None = None,
        model_size: str = "small",
    ) -> tuple[AlignmentSpan | None, ...]:
        seen.append(list(sentences))
        return tuple(None for _ in sentences)

    monkeypatch.setattr(alignment_module, "align_sentences", _fake_align)
    monkeypatch.setenv(SUBTITLE_ALIGNMENT_ENV, "1")
    preparation = _speech(SpeechMode.NARRATOR_VOICEOVER, (None, "第一句。第二句。"))

    # frozen 重放口径：cues 已断好句，整条当一个 utterance，不再切。
    build_aligned_timing(
        project=_project(),
        audio_path=Path("narration.wav"),
        audio_content_digest="sha256-v1:" + "a" * 64,
        preparation=preparation,
        cache_dir=tmp_path,
        subtitle_sentences_prepared=True,
    )
    assert seen == [["第一句。第二句。"]]

    # 生成口径：现场断句，两句各自对齐。
    build_aligned_timing(
        project=_project(),
        audio_path=Path("narration.wav"),
        audio_content_digest="sha256-v1:" + "a" * 64,
        preparation=preparation,
        cache_dir=tmp_path,
        subtitle_sentences_prepared=False,
    )
    assert seen[-1] == ["第一句。", "第二句。"]


# ---------- alignment_source_media 音频源选择 ----------


def test_alignment_source_prefers_narration_audio_over_video() -> None:
    narration = _media("audio/n.wav", kind="a", duration=12.0)
    video = _media("reference_videos/E1U01.mp4", kind="v", duration=30.0)

    source = alignment_source_media(narration, video, provider_audio_enabled=True)

    assert source is narration


def test_alignment_source_falls_back_to_video_audio_for_post_production() -> None:
    # 对白剧没有 ArcReel 合成的旁白：对白在视频自己的音轨里，对着它对齐。
    video = _media("reference_videos/E1U01.mp4", kind="v", duration=30.0)

    source = alignment_source_media(None, video, provider_audio_enabled=True)

    assert source is video


def test_alignment_source_none_when_video_has_no_provider_audio() -> None:
    # 视频没生成音频（generate_audio=False）时没有可对齐的声源。
    video = _media("reference_videos/E1U01.mp4", kind="v", duration=30.0)

    assert alignment_source_media(None, video, provider_audio_enabled=False) is None


def test_alignment_source_none_without_any_source() -> None:
    assert alignment_source_media(None, None, provider_audio_enabled=True) is None


# ---------- 模型加载的失败转换与并发安全 ----------


class _FakeWhisperModule:
    """替身 faster_whisper 模块：只暴露 WhisperModel 构造入口。"""

    def __init__(self, whisper_model: type) -> None:
        self.WhisperModel = whisper_model


def test_load_model_construction_failure_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # 挂载缓存上并发读同一 model.bin 曾触发 RuntimeError；它必须转换成
    # AlignmentUnavailable 让调用方回退机械分配，而不是冒到 API 层变 500。
    alignment_module._MODEL_CACHE.clear()

    class _Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("Model file.bin is incomplete")

    monkeypatch.setattr(alignment_module.importlib, "import_module", lambda name: _FakeWhisperModule(_Boom))

    with pytest.raises(AlignmentUnavailable, match="model load failed"):
        alignment_module._load_model("small")

    assert alignment_module._MODEL_CACHE == {}


def test_load_model_concurrent_first_load_constructs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # 一个分集多个单元同时对齐时会并发首次加载；无锁会重复构造模型
    # （每个实例数百 MB）并在挂载缓存上并发读同一文件。双检锁保证只构造一次。
    alignment_module._MODEL_CACHE.clear()
    constructed: list[str] = []

    class _SlowModel:
        def __init__(self, model_size: str, device: str, compute_type: str) -> None:
            time.sleep(0.05)
            constructed.append(model_size)

    monkeypatch.setattr(alignment_module.importlib, "import_module", lambda name: _FakeWhisperModule(_SlowModel))

    models: list[object] = []
    guard = threading.Lock()

    def _load() -> None:
        model = alignment_module._load_model("small")
        with guard:
            models.append(model)

    threads = [threading.Thread(target=_load) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert constructed == ["small"]
    assert len(models) == 8
    assert all(model is models[0] for model in models)


def test_align_sentences_setup_failure_raises_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 解码阶段（模型加载之后、转写之前）的意外失败同样不得中断物化。
    audio = tmp_path / "narration.wav"
    audio.write_bytes(b"RIFFfake")

    def _decode_boom(path: Path) -> None:
        raise OSError("ffmpeg decode exploded")

    monkeypatch.setattr(
        alignment_module.importlib.util,
        "find_spec",
        lambda name: object() if name == "faster_whisper" else None,
    )

    def _load_stub(model_size: str) -> _AlignmentModel:
        return cast(_AlignmentModel, object())

    with pytest.raises(AlignmentUnavailable, match="alignment setup failed"):
        align_sentences(audio, ["你好世界"], language="zh", model_loader=_load_stub, audio_decoder=_decode_boom)


def test_align_sentences_cached_concurrent_calls_run_alignment_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 打开剪辑页时多个接口并发物化同一批单元：同一键的对齐只算一次，其余线程等结果。
    reset_memory_cache()
    alignment_module._INFLIGHT.clear()
    calls: list[int] = []
    guard = threading.Lock()

    def _slow_align(
        audio_path: Path,
        sentences: Sequence[str],
        *,
        language: str | None = None,
        model_size: str = "small",
    ) -> tuple[AlignmentSpan | None, ...]:
        with guard:
            calls.append(1)
        time.sleep(0.05)
        return (AlignmentSpan(1_000_000, 2_000_000), None)

    monkeypatch.setattr(alignment_module, "align_sentences", _slow_align)
    digest = "sha256-v1:" + "b" * 64

    results: list[tuple[AlignmentSpan | None, ...]] = []
    result_guard = threading.Lock()

    def _call() -> None:
        spans = align_sentences_cached(
            Path("narration.wav"),
            ["第一句。", "第二句。"],
            language="zh",
            audio_content_digest=digest,
            cache_dir=tmp_path,
        )
        with result_guard:
            results.append(spans)

    threads = [threading.Thread(target=_call) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert len(results) == 6
    assert all(spans == results[0] for spans in results)


def test_align_sentences_cached_waiter_recomputes_after_owner_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 先到者能力缺席（不落缓存）时，等待者不能拿着空结果返回，也不能干等：依次补算。
    reset_memory_cache()
    alignment_module._INFLIGHT.clear()
    owner_started = threading.Event()
    release_owner = threading.Event()
    attempts: list[int] = []
    guard = threading.Lock()

    def _flaky_align(
        audio_path: Path,
        sentences: Sequence[str],
        *,
        language: str | None = None,
        model_size: str = "small",
    ) -> tuple[AlignmentSpan | None, ...]:
        with guard:
            attempts.append(1)
            first = len(attempts) == 1
        if first:
            owner_started.set()
            release_owner.wait(5)
            raise AlignmentUnavailable("first attempt fails")
        return (AlignmentSpan(5_000_000, 6_000_000), None)

    monkeypatch.setattr(alignment_module, "align_sentences", _flaky_align)
    digest = "sha256-v1:" + "c" * 64

    owner_error: list[AlignmentUnavailable] = []

    def _owner() -> None:
        try:
            align_sentences_cached(
                Path("narration.wav"),
                ["第一句。"],
                language="zh",
                audio_content_digest=digest,
                cache_dir=tmp_path,
            )
        except AlignmentUnavailable as exc:
            owner_error.append(exc)

    def _waiter() -> tuple[AlignmentSpan | None, ...]:
        return align_sentences_cached(
            Path("narration.wav"),
            ["第一句。"],
            language="zh",
            audio_content_digest=digest,
            cache_dir=tmp_path,
        )

    owner = threading.Thread(target=_owner)
    owner.start()
    assert owner_started.wait(5)
    waiter = threading.Thread(target=lambda: waiter_results.append(_waiter()))
    waiter_results: list[tuple[AlignmentSpan | None, ...]] = []
    waiter.start()
    time.sleep(0.05)  # 等待者已进入 event.wait()
    release_owner.set()
    owner.join(5)
    waiter.join(5)

    assert len(owner_error) == 1
    assert len(attempts) == 2  # 先到者失败后等待者补算一次
    assert waiter_results == [(AlignmentSpan(5_000_000, 6_000_000), None)]
    # 补算成功才落缓存。
    key = cache_key(model_size="small", language="zh", audio_content_digest=digest, sentences=["第一句。"])
    reset_memory_cache()
    assert load_cached_spans(tmp_path, key) == ((5_000_000, 6_000_000), None)
