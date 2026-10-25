"""字幕句级对齐结果的缓存。

对齐是确定性纯计算：同一段音频（以 content_digest 标识）、同一串句子、同一模型与
语种，结果永远相同。写入路径（presentation_read_model）与校验路径（artifact_planner
的 frozen 重放）各自都会触发一次对齐，缓存让第二次起重放零 ASR 成本；同时保证
「生成时算出的 spans」与「重放时算出的 spans」逐字节一致，不会一侧成功一侧失败
造成字幕 artifact 反复 stale。

缓存布局：``<cache_dir>/.arcreel-cache/subtitle-alignment/<digest>.json``，其中
``cache_dir`` 是项目目录。内容是 ``{"schema": 1, "spans": [[start_us, end_us] | null, ...]}``。
只缓存成功产出（含部分句子匹配不上的 None）；对齐能力缺席（依赖未装、音频读不出）
抛异常不写缓存，让下次重试。

进程内还有一层等价的内存缓存：同一进程里 planner 与 read model 交替调用时不再碰盘。
本模块只依赖标准库，不 import ``lib.speech`` 的任何模块——span 以裸元组进出，
:class:`lib.speech.subtitle_alignment.AlignmentSpan` 的转换由调用侧完成。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

#: 缓存内容的结构版本；键算法或落盘格式变化时递增，旧文件自然失效。
CACHE_SCHEMA = 1

#: 缓存落在项目目录下的隐藏根（与 ``.arcreel`` / ``.arcreel_artifacts.json`` 同一家风），
#: 不参与 artifact manifest 的登记扫描。
ALIGNMENT_CACHE_ROOT = ".arcreel-cache"

CACHE_SUBDIR = "subtitle-alignment"

#: (start_us, end_us)；匹配不上的句子为 None。
SpanTuple = tuple[int, int] | None

_MEMORY_CACHE: dict[str, tuple[SpanTuple, ...]] = {}


def cache_key(
    *,
    model_size: str,
    language: str | None,
    audio_content_digest: str,
    sentences: Sequence[str],
) -> str:
    """对齐结果的缓存键：模型、语种、音频内容与句子序列的摘要。"""

    digest = hashlib.sha256()
    digest.update(f"schema={CACHE_SCHEMA}\0".encode())
    digest.update(f"model={model_size}\0".encode())
    digest.update(f"language={language or 'auto'}\0".encode())
    digest.update(f"audio={audio_content_digest}\0".encode())
    for sentence in sentences:
        digest.update(sentence.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / ALIGNMENT_CACHE_ROOT / CACHE_SUBDIR / f"{key}.json"


def load_cached_spans(cache_dir: Path, key: str) -> tuple[SpanTuple, ...] | None:
    """按键取缓存的对齐结果；未命中或文件损坏时返回 None（调用方重算）。"""

    memory = _MEMORY_CACHE.get(key)
    if memory is not None:
        return memory
    path = _cache_path(cache_dir, key)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        logger.warning("字幕对齐缓存损坏，忽略: %s", path)
        return None
    if not isinstance(payload, dict) or payload.get("schema") != CACHE_SCHEMA:
        return None
    raw_spans = payload.get("spans")
    if not isinstance(raw_spans, list):
        return None
    spans: list[SpanTuple] = []
    for item in raw_spans:
        if item is None:
            spans.append(None)
            continue
        if not isinstance(item, list) or len(item) != 2:
            return None
        start_us, end_us = item
        if type(start_us) is not int or type(end_us) is not int:
            return None
        spans.append((start_us, end_us))
    result = tuple(spans)
    _MEMORY_CACHE[key] = result
    return result


def store_cached_spans(cache_dir: Path, key: str, spans: tuple[SpanTuple, ...]) -> None:
    """把对齐结果写入缓存；写盘失败只记日志，不影响调用方。

    mkstemp + os.replace 与 :mod:`lib.agent.profile_manifest` 同一套路：不可预测的
    临时名 + same dir，拒绝被预置 symlink 的攻击面。
    """

    _MEMORY_CACHE[key] = spans
    path = _cache_path(cache_dir, key)
    payload = {
        "schema": CACHE_SCHEMA,
        "spans": [[span[0], span[1]] if span is not None else None for span in spans],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_str = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
            os.replace(tmp_str, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_str)
            raise
    except OSError as exc:
        logger.warning("字幕对齐缓存写入失败: %s (%s)", path, exc)


def reset_memory_cache() -> None:
    """清空进程内缓存；测试用。"""

    _MEMORY_CACHE.clear()


__all__ = [
    "ALIGNMENT_CACHE_ROOT",
    "CACHE_SCHEMA",
    "CACHE_SUBDIR",
    "SpanTuple",
    "cache_key",
    "load_cached_spans",
    "reset_memory_cache",
    "store_cached_spans",
]
