"""字幕的句级强制对齐：用旁白配音的实测波形为已知句子逐条测出起止时间。

与 :class:`lib.speech.speech_presentation.MechanicalSubtitleTiming` 按阅读单位比例顺排不同，
这里以配音音频为事实来源：ASR（faster-whisper）转写出带词级时间戳的词流，再把已知的
字幕句子按顺序匹配到词流上。字幕文本就是 TTS 的合成输入，不是猜出来的——匹配只为定位，
所以数字、专有名词不会因识别误差对不上（识别错的词按跳过容忍处理，不影响其他句子）。

匹配不上的句子由 :class:`AlignedSubtitleTiming` 按阅读单位在相邻锚点之间的空档里补；
整段对不上或对齐能力缺席时整体回退机械分配，流水线不中断。

对齐依赖 faster-whisper，是可选能力（``subtitle-alignment`` extra，见 pyproject）：
未安装时 :func:`align_sentences` 抛 :class:`AlignmentUnavailable`，行为与不装依赖一致。
模型推理是重计算，:meth:`AlignedSubtitleTiming.distribute` 是阻塞调用，
在 async 上下文里必须经 ``asyncio.to_thread`` 包一层。

接入（部署级开关 ``ARCREEL_SUBTITLE_ALIGNMENT``，默认关）：开着且注入了 timing 的
materialize 走对齐，没开或注入不了时走机械分配，行为与接入前一致。:func:`build_aligned_timing` 是
写入路径（presentation_read_model）与校验路径（artifact_planner frozen 重放）
共用的接线函数，两侧必须注入同一策略，否则已存字幕会被判不一致而反复重生成。

对齐的音频源由 :func:`alignment_source_media` 选：TTS 变体用旁白配音；后补配音
变体（对白剧）没有 ArcReel 合成的旁白，对白由视频模型生成在单元视频自己的音轨里，
字幕对着视频音轨对齐——这正是机械分配失真最严重的场景（字数比例与真实发音无关，
实测整体偏移可达数秒）。
"""

from __future__ import annotations

import importlib.util
import logging
import math
import os
import subprocess
import threading
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from lib.speech.alignment_cache import cache_key, load_cached_spans, store_cached_spans
from lib.speech.speech_artifact_provenance import (
    SubtitleUtteranceEvidence,
    project_subtitle_utterances,
)
from lib.speech.speech_composition import SpeechPreparation
from lib.speech.speech_presentation import MechanicalSubtitleTiming, PresentationMedia, SubtitleCue
from lib.speech.subtitle_sentences import subtitle_reading_units

logger = logging.getLogger(__name__)

#: 默认对齐模型：small 是 CPU 上中文准确率与耗时的平衡点，base 快但中文明显更差。
DEFAULT_ALIGNMENT_MODEL = "small"

#: 部署级开关：字幕句级强制对齐。缺省（未设置）关——字幕 basis 与机械分配路径都不因部署变化；
#: 设为 1/true/yes/on 开，其余值关。字幕计时策略是技术机制而非创作参数，按部署统一取舍，
#: 不做项目级开关（docs/adr/0108）。
SUBTITLE_ALIGNMENT_ENV = "ARCREEL_SUBTITLE_ALIGNMENT"

#: 项目 source_language → Whisper 语种码。存量项目存过「中文」这类标签，一并收录。
_WHISPER_LANGUAGE_BY_SOURCE: dict[str, str] = {
    "zh": "zh",
    "en": "en",
    "vi": "vi",
    "中文": "zh",
    "汉语": "zh",
    "chinese": "zh",
    "english": "en",
    "vietnamese": "vi",
    "越南语": "vi",
}

_NUMBER_WORDS: tuple[tuple[str, str], ...] = (
    # 中文数字（含口语「两」）。
    ("零", "0"),
    ("一", "1"),
    ("二", "2"),
    ("两", "2"),
    ("三", "3"),
    ("四", "4"),
    ("五", "5"),
    ("六", "6"),
    ("七", "7"),
    ("八", "8"),
    ("九", "9"),
    # 越南语数词：Whisper 的越南语输出会把它们跨语种错识成中文数字，统一成数字才对得上。
    ("không", "0"),
    ("một", "1"),
    ("hai", "2"),
    ("ba", "3"),
    ("bốn", "4"),
    ("năm", "5"),
    ("sáu", "6"),
    ("bảy", "7"),
    ("tám", "8"),
    ("chín", "9"),
    ("mười", "10"),
    # 英语数词。
    ("zero", "0"),
    ("one", "1"),
    ("two", "2"),
    ("three", "3"),
    ("four", "4"),
    ("five", "5"),
    ("six", "6"),
    ("seven", "7"),
    ("eight", "8"),
    ("nine", "9"),
    ("ten", "10"),
)

_MAX_SKIP_CHARS = 8
"""一条句子的对齐编辑预算下限（替换/多字/漏字合计）；长句按长度的三分之一放宽。"""

_COST_MATCH = -2.0
"""精确匹配奖励：负成本让「找到真实字符」成为主导目标——词流里真实存在的字符序列
永远赛过拿噪音顶替的路径，与噪音段长短无关。"""

_COST_SUB = 2.0
"""替换成本（ASR 听错，如「又哭穷」→「有苦求」）。"""

_COST_INSERT = 1.0
"""词流多字成本（口头禅、杂音）：最便宜的非匹配操作。"""

_COST_DELETE = 2.5
"""目标漏字成本（ASR 漏识别）：比替换更贵——听错的字至少还标出一个时间段。"""

_MIN_MATCH_RATIO = 0.5
"""真实对上（精确匹配）的字符占比底线：低于此判失败，防止假匹配到噪音上。"""

_MIN_CUE_US = 1
"""一条字幕的最短显示时长（微秒）：对齐结果可能极短，但不允许为零长。"""

_DECODE_TIMEOUT_SECONDS = 120.0
"""随包 ffmpeg 解码一段配音的超时：按分钟级音频留足余量。"""


class AlignmentUnavailable(RuntimeError):
    """对齐能力缺席：依赖未安装、音频文件不在或读不出时间戳。"""


@dataclass(frozen=True, slots=True)
class AlignmentSpan:
    """一条句子在配音音频里的实测起止（成片时间微秒，相对音频起点）。"""

    start_us: int
    end_us: int


@dataclass(frozen=True, slots=True)
class _StreamChar:
    """词流展开成的字符级时间轴：字符继承所在词的时间戳。"""

    char: str
    start_us: int
    end_us: int


class _AlignmentWord(Protocol):
    """faster-whisper 的词级时间戳条目；结构对齐，避免对可选依赖的类型硬依赖。"""

    word: str
    start: float
    end: float


class _AlignmentSegment(Protocol):
    @property
    def words(self) -> Sequence[_AlignmentWord] | None: ...


class _AlignmentModel(Protocol):
    def transcribe(
        self,
        audio: str | np.ndarray,
        *,
        language: str | None,
        word_timestamps: bool,
        vad_filter: bool,
        beam_size: int,
    ) -> tuple[Iterable[_AlignmentSegment], object]: ...


def _canonicalize_number_words(text: str) -> str:
    """把中、越、英的数词统一翻成阿拉伯数字。

    Whisper 的逆文本正则化与跨语种错识都会让数字在几种形式间跳：
    「二零二三」↔「2023」、越南语「một」被识成中文「一」。规范化到数字后两侧才对得上。
    长词优先替换，避免「一十」被「一」抢先。
    """

    for word, digit in sorted(_NUMBER_WORDS, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(word, digit)
    return text


def _normalized_chars(text: str) -> str:
    """对齐用的规范化字符串：NFC、小写、数词翻数字、变音符折叠，只留字母与数字。

    按 Unicode 类别过滤：标点（含全角句读，其 East_Asian_Width 也是 W）与空白全部丢弃——
    断句已经带走标点，ASR 词上的附着标点不该影响匹配。数词先翻成数字（NFC 形态下查表），
    再折叠组合音符（Mn），让「phủ」与听错的「phụ」落在同一个骨架上；
    折叠只影响匹配，不改动字幕原文。
    """

    normalized = _canonicalize_number_words(unicodedata.normalize("NFC", text).lower())
    stripped = "".join(char for char in unicodedata.normalize("NFD", normalized) if unicodedata.category(char) != "Mn")
    return "".join(
        char for char in unicodedata.normalize("NFC", stripped) if unicodedata.category(char)[0] in {"L", "N"}
    )


def _word_char_stream(words: Sequence[tuple[str, float, float]]) -> tuple[_StreamChar, ...]:
    """把 ASR 词流（文本、起、止，单位秒）展开成字符级时间轴。"""

    stream: list[_StreamChar] = []
    for text, start, end in words:
        chars = _normalized_chars(text)
        if not chars:
            continue
        start_us = round(start * 1_000_000)
        end_us = max(round(end * 1_000_000), start_us)
        stream.extend(_StreamChar(char=char, start_us=start_us, end_us=end_us) for char in chars)
    return tuple(stream)


def match_sentences_to_stream(
    sentences: Sequence[str], stream: Sequence[_StreamChar]
) -> tuple[AlignmentSpan | None, ...]:
    """按顺序把已知句子匹配到字符流上，返回与句子一一对应的起止（匹配不上为 None）。

    每条句子从游标处向后做**有界编辑距离对齐**：目标字符与词流字符逐列比对——
    匹配零成本；替换（ASR 听错，如「又哭穷」→「有苦求」）、词流多字（口头禅、杂音）、
    目标漏字（ASR 漏识别）各计一次编辑。总编辑数超过 ``max(8, 句长三分之一)``
    判该句失败。对齐路径上第一个与最后一个真正对上（含替换）的词流字符给出起止。
    游标只前进不回溯，重复出现的句子因此各自消耗各自的一段。
    """

    spans: list[AlignmentSpan | None] = []
    cursor = 0
    for sentence in sentences:
        target = _normalized_chars(sentence)
        if not target:
            spans.append(None)
            continue
        span, cursor = _align_sentence(target, stream, cursor)
        spans.append(span)
    return tuple(spans)


def _align_sentence(target: str, stream: Sequence[_StreamChar], cursor: int) -> tuple[AlignmentSpan | None, int]:
    """把一个句子的目标字符对齐到词流上；返回 (起止, 新游标)，失败时游标不动。

    成本设计让「精确匹配」压倒一切：跳过噪音（多字）最便宜，替换与漏字都更贵，
    于是词流里真实存在的字符序列永远赛过拿噪音顶替的路径。另要求至少一半目标字符
    真实对上，防止短句靠连续替换假匹配到噪音段上。
    """

    budget = max(_MAX_SKIP_CHARS, len(target) // 3)
    min_matches = math.ceil(len(target) * _MIN_MATCH_RATIO)
    # 搜索窗口：游标之后、目标长度加编辑预算之内——更远的对齐没有语义意义。
    window_end = min(len(stream), cursor + len(target) + budget)
    if window_end <= cursor:
        return None, cursor
    width = window_end - cursor

    # dp[i][k]：目标前 i 个字符对齐到词流前 k 个字符的最小成本。
    # 移动：对角线（匹配 _COST_MATCH / 替换 _COST_SUB）、向上（漏字 _COST_DELETE）、
    # 向左（多字 _COST_INSERT）。匹配是负成本，对齐因此以「多找真实字符」为先。
    dp = [[0.0] * (width + 1) for _ in range(len(target) + 1)]
    for k in range(1, width + 1):
        dp[0][k] = k * _COST_INSERT
    for i in range(1, len(target) + 1):
        dp[i][0] = i * _COST_DELETE
        target_char = target[i - 1]
        row, prev = dp[i], dp[i - 1]
        for k in range(1, width + 1):
            diagonal = prev[k - 1] + (_COST_MATCH if target_char == stream[cursor + k - 1].char else _COST_SUB)
            row[k] = min(diagonal, prev[k] + _COST_DELETE, row[k - 1] + _COST_INSERT)

    final = dp[len(target)]
    best_k = min((k for k in range(1, width + 1)), key=lambda k: (final[k], k))
    if final[best_k] > budget:
        return None, cursor

    # 回溯：优先对角线（真正对上），否则向上（漏字），再向左（多字）。
    aligned: list[int] = []
    matches = 0
    i, k = len(target), best_k
    while i > 0 or k > 0:
        if i > 0 and k > 0:
            same = target[i - 1] == stream[cursor + k - 1].char
            if dp[i][k] == dp[i - 1][k - 1] + (_COST_MATCH if same else _COST_SUB):
                aligned.append(cursor + k - 1)
                matches += 1 if same else 0
                i, k = i - 1, k - 1
                continue
        if i > 0 and dp[i][k] == dp[i - 1][k] + _COST_DELETE:
            i -= 1
            continue
        k -= 1
    if len(aligned) < min_matches or matches < min_matches:
        return None, cursor

    first, last = min(aligned), max(aligned)
    return AlignmentSpan(start_us=stream[first].start_us, end_us=stream[last].end_us), last + 1


def align_sentences(
    audio_path: Path,
    sentences: Sequence[str],
    *,
    language: str | None = None,
    model_size: str = DEFAULT_ALIGNMENT_MODEL,
    model_loader: Callable[[str], _AlignmentModel] | None = None,
    audio_decoder: Callable[[Path], np.ndarray] | None = None,
) -> tuple[AlignmentSpan | None, ...]:
    """对一段配音音频做句级对齐；能力缺席时抛 :class:`AlignmentUnavailable`。

    ``language`` 为 None 时交给 ASR 自动判别（中英混排内容自动判别通常可靠；
    自动判别多一次前向消耗，已知语种时显式传入更稳）。模型实例按型号缓存，
    同一进程内重复对齐不重复加载。``model_loader`` / ``audio_decoder`` 是模型加载
    与解码两步的注入缝（None 用内置实现），供测试模拟加载/解码失败。
    """

    if not sentences:
        return ()
    path = Path(audio_path)
    if not path.is_file():
        raise AlignmentUnavailable(f"narration audio not found: {path}")
    if importlib.util.find_spec("faster_whisper") is None:  # 可选依赖缺席：调用方回退机械分配
        raise AlignmentUnavailable("faster-whisper is not installed")

    try:
        model = (model_loader or _load_model)(model_size)
        audio = (audio_decoder or _decode_audio_16k_mono)(path)
    except AlignmentUnavailable:
        raise
    except Exception as exc:  # 模型加载/解码的意外失败同样回退机械分配，不中断物化
        raise AlignmentUnavailable(f"alignment setup failed for {path}: {exc}") from exc
    try:
        segments, _info = model.transcribe(
            audio,
            language=language,
            word_timestamps=True,
            vad_filter=True,
            beam_size=2,
        )
        words = [(word.word, word.start, word.end) for segment in segments for word in (segment.words or [])]
    except Exception as exc:  # ASR 运行时报错一律视为对不齐，不让流水线中断
        raise AlignmentUnavailable(f"alignment failed for {path}: {exc}") from exc
    if not words:
        raise AlignmentUnavailable(f"alignment produced no words for {path}")
    return match_sentences_to_stream(sentences, _word_char_stream(words))


def _decode_audio_16k_mono(path: Path) -> np.ndarray:
    """用随包 ffmpeg 把任意格式音频解成 16kHz 单声道 float32（Whisper 的输入约定）。

    不走 faster-whisper 内部的 PyAV 解码：它的 ``av.open`` 签名与 PyAV 19.x 不兼容
    （``metadata_errors``），且格式覆盖也不全。随包 ffmpeg 全格式可解，也是仓库里
    解码音频的既定通道（:mod:`lib.infra.ffmpeg`）。
    """

    from lib.infra.ffmpeg import FfmpegUnavailableError, ffmpeg_executable

    try:
        executable = ffmpeg_executable()
    except FfmpegUnavailableError as exc:
        raise AlignmentUnavailable(f"bundled ffmpeg unavailable: {exc}") from exc
    try:
        result = subprocess.run(
            [executable, "-nostdin", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=_DECODE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AlignmentUnavailable(f"audio decode timed out for {path}") from exc
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-200:]
        raise AlignmentUnavailable(f"audio decode failed for {path}: {detail}")
    return np.frombuffer(result.stdout, dtype=np.float32)


def _load_model(model_size: str) -> _AlignmentModel:
    """按型号缓存 Whisper 模型；首次加载从本地缓存读，缺失时下载。

    加载持双检锁：物化可能并发触发（一个分集多个单元同时对齐），无锁并发首次
    加载会重复构造模型（每个实例数百 MB），且并发读挂载缓存上的同一 model.bin
    会触发读失败（曾致 edit-overview 500）。锁保证只加载一次，其余线程等缓存。
    构造失败转 :class:`AlignmentUnavailable`，调用方回退机械分配。
    """

    global _MODEL_CACHE
    model = _MODEL_CACHE.get(model_size)
    if model is None:
        with _MODEL_LOAD_LOCK:
            model = _MODEL_CACHE.get(model_size)
            if model is None:
                # faster-whisper 是可选依赖：经 importlib 动态取类，静态检查不依赖它装没装。
                module = importlib.import_module("faster_whisper")
                logger.info("加载对齐模型 faster-whisper/%s", model_size)
                try:
                    model = module.WhisperModel(model_size, device="cpu", compute_type="int8")
                except Exception as exc:
                    raise AlignmentUnavailable(f"alignment model load failed: {model_size}: {exc}") from exc
                _MODEL_CACHE[model_size] = model
    return model


_MODEL_CACHE: dict[str, _AlignmentModel] = {}
_MODEL_LOAD_LOCK = threading.Lock()


def whisper_language_for(source_language: object) -> str | None:
    """项目 ``source_language`` → Whisper 语种码；不认识或缺失返回 None（自动判别）。"""

    if not isinstance(source_language, str):
        return None
    return _WHISPER_LANGUAGE_BY_SOURCE.get(source_language.strip().lower())


def subtitle_alignment_enabled() -> bool:
    """部署是否开着字幕句级对齐（环境变量 ``ARCREEL_SUBTITLE_ALIGNMENT``）。

    缺省关：字幕计时策略是部署级技术机制（docs/adr/0108），按部署统一取舍，
    不随项目变化；部署方显式开启以接受每次生成的预热 ASR 成本。
    """

    env = os.environ.get(SUBTITLE_ALIGNMENT_ENV)
    if env is None:
        return False
    return env.strip().lower() in {"1", "true", "yes", "on"}


def align_sentences_cached(
    audio_path: Path,
    sentences: Sequence[str],
    *,
    language: str | None,
    audio_content_digest: str,
    cache_dir: Path,
    model_size: str = DEFAULT_ALIGNMENT_MODEL,
) -> tuple[AlignmentSpan | None, ...]:
    """:func:`align_sentences` 的缓存版：命中跳过 ASR，未命中算完落盘。

    ``audio_content_digest`` 是配音文件的内容摘要（``PresentationMedia`` 的
    ``evidence.content_digest``），与句子序列、模型、语种共同构成缓存键。
    对齐能力缺席时抛 :class:`AlignmentUnavailable`，不写缓存。

    同一键的对齐在进程内 single-flight：打开剪辑页时 edit-timelines、preview-media、
    presentations 会并发物化同一批单元，无去重时每个请求各跑一遍 ASR（CPU 争抢下
    冷启动从约一分钟劣化到七八分钟）。先到者计算，其余线程等其结果；先到者能力
    缺席未落缓存时，等待者依次补算（与无去重时逐个失败的行为一致）。
    """

    key = cache_key(
        model_size=model_size,
        language=language,
        audio_content_digest=audio_content_digest,
        sentences=sentences,
    )
    cached = load_cached_spans(cache_dir, key)
    if cached is not None:
        return tuple(AlignmentSpan(start_us=span[0], end_us=span[1]) if span is not None else None for span in cached)
    while True:
        with _INFLIGHT_LOCK:
            event = _INFLIGHT.get(key)
            if event is None:
                event = threading.Event()
                _INFLIGHT[key] = event
                owner = True
            else:
                owner = False
        if owner:
            break
        event.wait()
        cached = load_cached_spans(cache_dir, key)
        if cached is not None:
            return tuple(
                AlignmentSpan(start_us=span[0], end_us=span[1]) if span is not None else None for span in cached
            )
    try:
        spans = align_sentences(audio_path, sentences, language=language, model_size=model_size)
        store_cached_spans(
            cache_dir,
            key,
            tuple((span.start_us, span.end_us) if span is not None else None for span in spans),
        )
        return spans
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(key, None)
        event.set()


#: 进程内正在计算的缓存键 → 完成事件；:func:`align_sentences_cached` 的 single-flight 用。
_INFLIGHT: dict[str, threading.Event] = {}
_INFLIGHT_LOCK = threading.Lock()


def alignment_source_media(
    narration_audio: PresentationMedia | None,
    video: PresentationMedia | None,
    *,
    provider_audio_enabled: bool,
) -> PresentationMedia | None:
    """选字幕对齐的音频源：优先 TTS 旁白音频；没有旁白时回退到视频自己的音轨。

    TTS 变体（use_tts）里响的是旁白配音，字幕跟着它走。后补配音变体
    （post_production，对白剧）没有 ArcReel 合成的旁白，对白由视频模型直接
    生成进单元视频的音轨（版本记录 ``generate_audio``）——成片里响的就是
    这条音轨，字幕对着它对齐。视频没生成音频时没有可对齐的声源，返回 None
    （调用方走机械分配）。ASR 本身是最终判据：音轨里没有话音时转写不出词，
    :func:`align_sentences` 抛 :class:`AlignmentUnavailable`，同样回退机械分配。
    """

    if narration_audio is not None:
        return narration_audio
    return video if provider_audio_enabled else None


def build_aligned_timing(
    *,
    project: Mapping[str, object],
    audio_path: Path,
    audio_content_digest: str,
    preparation: SpeechPreparation,
    cache_dir: Path,
    subtitle_sentences_prepared: bool = False,
) -> AlignedSubtitleTiming | None:
    """写入路径与校验路径共用的字幕对齐接线。

    部署没开对齐时返回 None（调用方传 ``timing=None``，走机械分配，行为同接入前）。
    ``project`` 只用于解析 ``source_language``（Whisper 语种码），开关不看项目。
    开着时预先算好 spans 并注入策略——预计算是阻塞 CPU 计算，async 调用方必须把
    本函数经 ``asyncio.to_thread`` 包一层。预计算的句子序列与 materialize 内部投影
    同口径，由 ``subtitle_sentences_prepared`` 保持一致。

    对齐能力缺席（依赖未装、音频读不出、ASR 失败）时记日志并返回 None：本次物化
    退机械分配，下次（依赖就绪或缓存可写后）自然回到对齐。
    """

    if not subtitle_alignment_enabled():
        return None
    language = whisper_language_for(project.get("source_language"))
    utterances = project_subtitle_utterances(preparation, subtitle_sentences_prepared=subtitle_sentences_prepared)
    try:
        spans = align_sentences_cached(
            audio_path,
            [utterance.text for utterance in utterances],
            language=language,
            audio_content_digest=audio_content_digest,
            cache_dir=cache_dir,
        )
    except AlignmentUnavailable as exc:
        logger.warning("字幕对齐缺席，回退机械分配: %s", exc)
        return None
    return AlignedSubtitleTiming(audio_path=audio_path, language=language, precomputed_spans=spans)


@dataclass(frozen=True, slots=True)
class AlignedSubtitleTiming:
    """用配音实测波形给已知句子定时间的字幕时序策略。

    构造时注入音频路径；``language`` 显式指定语种（Whisper 语种码），None 表示自动判别。
    对齐结果与机械分配混合使用：匹配上的句子用实测起止，匹配不上的按阅读单位在相邻
    实测锚点之间的空档里补；全部匹配不上或对齐能力缺席时整体回退机械分配。

    ``precomputed_spans`` 供 async 调用方在 ``asyncio.to_thread`` 里预先算好再注入
    （对齐是阻塞 CPU 计算，materialize 本身保持纯同步）；注入后 distribute 不再跑 ASR。
    预计算序列与 ``utterances`` 数量不符时忽略预计算值，退回现场对齐。
    """

    audio_path: Path
    language: str | None = None
    model_size: str = DEFAULT_ALIGNMENT_MODEL
    policy_version: int = 1
    precomputed_spans: tuple[AlignmentSpan | None, ...] | None = None

    def __post_init__(self) -> None:
        if not Path(self.audio_path).name:
            raise ValueError("audio_path must be a non-empty path")

    @property
    def basis_identity(self) -> dict[str, object]:
        return {
            "kind": "aligned-sentence-forced-alignment",
            "version": self.policy_version,
            "model": self.model_size,
            "language": self.language or "auto",
        }

    def distribute(
        self,
        utterances: tuple[SubtitleUtteranceEvidence, ...],
        *,
        boundary_microseconds: int,
    ) -> tuple[SubtitleCue, ...]:
        if type(boundary_microseconds) is not int or boundary_microseconds <= 0:
            raise ValueError("boundary_microseconds must be a positive integer")
        if not utterances:
            return ()
        if self.precomputed_spans is not None:
            if len(self.precomputed_spans) == len(utterances):
                return _distribute_with_anchors(
                    utterances, self.precomputed_spans, boundary_microseconds=boundary_microseconds
                )
            logger.warning(
                "预计算字幕对齐 spans 数量(%d)与 utterances(%d)不符，退回现场对齐",
                len(self.precomputed_spans),
                len(utterances),
            )
        try:
            spans = align_sentences(
                self.audio_path,
                [utterance.text for utterance in utterances],
                language=self.language,
                model_size=self.model_size,
            )
        except AlignmentUnavailable as exc:
            logger.warning("字幕对齐缺席，回退机械分配: %s", exc)
            return MechanicalSubtitleTiming().distribute(utterances, boundary_microseconds=boundary_microseconds)
        return _distribute_with_anchors(utterances, spans, boundary_microseconds=boundary_microseconds)


def _distribute_with_anchors(
    utterances: tuple[SubtitleUtteranceEvidence, ...],
    spans: tuple[AlignmentSpan | None, ...],
    *,
    boundary_microseconds: int,
) -> tuple[SubtitleCue, ...]:
    """实测锚点固定、空档按阅读单位补的字幕时序；无可用锚点时整体回退机械分配。"""

    anchors: dict[int, tuple[int, int]] = {}
    cursor = 0
    for index, span in enumerate(spans):
        if span is None:
            continue
        start = max(span.start_us, cursor)
        end = min(span.end_us, boundary_microseconds)
        if end <= start:
            continue
        anchors[index] = (start, end)
        cursor = end
    if not anchors:
        return MechanicalSubtitleTiming().distribute(utterances, boundary_microseconds=boundary_microseconds)

    weights = tuple(subtitle_reading_units(utterance.text) for utterance in utterances)
    resolved: list[tuple[int, int] | None] = [None] * len(utterances)
    for index, (start, end) in anchors.items():
        resolved[index] = (start, end)

    region_start = 0
    for index in range(len(utterances) + 1):
        anchor = anchors.get(index)
        if anchor is None and index < len(utterances):
            continue
        region_end = anchor[0] if anchor is not None else boundary_microseconds
        _fill_region(weights, resolved, region_start, region_end, stop_before=index)
        region_start = anchor[1] if anchor is not None else region_end

    cues: list[SubtitleCue] = []
    for utterance, span in zip(utterances, resolved, strict=True):
        if span is None:  # 退化空档（锚点紧挨）补不出正时长：并入机械分配保底
            return MechanicalSubtitleTiming().distribute(utterances, boundary_microseconds=boundary_microseconds)
        cues.append(
            SubtitleCue(
                start_microseconds=span[0],
                duration_microseconds=max(span[1] - span[0], _MIN_CUE_US),
                text=utterance.text,
                owner=utterance.owner,
                speaker=utterance.speaker,
            )
        )
    return tuple(cues)


def _fill_region(
    weights: tuple[int, ...],
    resolved: list[tuple[int, int] | None],
    region_start: int,
    region_end: int,
    *,
    stop_before: int,
) -> None:
    """把 ``[region_start, region_end)`` 按阅读单位分给这个空档里未锚定的句子。"""

    pending = [index for index in range(stop_before) if resolved[index] is None]
    if not pending or region_end <= region_start:
        return
    total_weight = sum(weights[index] for index in pending)
    cursor = region_start
    for index in pending:
        share = (
            (region_end - region_start) * weights[index] // total_weight
            if total_weight
            else (region_end - region_start) // len(pending)
        )
        end = min(cursor + max(share, _MIN_CUE_US), region_end)
        resolved[index] = (cursor, max(end, cursor + _MIN_CUE_US))
        cursor = end


__all__ = [
    "DEFAULT_ALIGNMENT_MODEL",
    "SUBTITLE_ALIGNMENT_ENV",
    "AlignedSubtitleTiming",
    "AlignmentSpan",
    "AlignmentUnavailable",
    "align_sentences",
    "align_sentences_cached",
    "build_aligned_timing",
    "match_sentences_to_stream",
    "subtitle_alignment_enabled",
    "whisper_language_for",
]
