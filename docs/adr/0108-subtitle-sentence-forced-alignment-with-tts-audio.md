---
status: accepted
---

# 字幕按配音实测波形做句级强制对齐，部署开关默认关，与机械分配同轨回退

> 本文替代 `docs/adr/0089` 里「字幕按阅读单位比例机械分配、不宣称逐句对齐」的默认口径：机械分配降级为兜底，呈现版本在对齐能力就绪时以「成片里实际会响的那条音轨」为事实来源定字幕起止——use_tts 是 TTS 旁白配音；post_production（对白剧）没有 ArcReel 合成的旁白，对白由视频模型直接生成在单元视频自己的音轨里，对着它对齐。

字幕时间以前由 `MechanicalSubtitleTiming` 按每句阅读单位比例顺排：把视频/配音总时长按字数比例分给各句。字数与实际发音时长不成比例（「二零二三年」五个字要念三秒），偏差在单元内累积，前几条大概齐、越往后飘得越远，实测漂移可达 1.7 秒。这是用户遇到的「声音与字幕不同步」的根因。

**字幕文本就是 TTS 的合成输入，对齐只测时间、不生成内容。** 已知文本 + 已知音频是强制对齐（forced alignment）的理想场景：ASR 只负责在波形上定位每句台词念到哪儿，识别错的内容（「浸」听成「净」、越南语「một」错识成中文「一」）按跳过容忍处理，不影响边界。三语（zh/en/vi，项目 i18n 既有范围）真实 TTS 音频实测：对齐误差平均 100–137ms、最大 360ms，机械分配平均 0.8–1.1s、最大 1.7s，改善约一个数量级。

**post_production（对白剧）的对齐源是单元视频自己的音轨。** 对白剧没有 ArcReel 合成的旁白，但视频模型生成单元时把对白直接演进了视频音轨（版本记录 `generate_audio`，prompt 里带各角色声音特征）——成片里响的就是这条音轨，字幕必须对着它。机械分配在这里失真最严重：实测 E2U03 第一句台词 6.4s 才开念，机械字幕从 0s 就摆上，整体偏移数秒。:func:`lib.speech.subtitle_alignment.alignment_source_media` 统一选源：有旁白音频用旁白（use_tts）；没有旁白且视频生成了音频时用视频音轨。ASR 本身是最终判据——音轨无话音（`generate_audio=false` 或纯环境声）时转写不出词，静默回退机械分配，与「没有对齐能力」同一条兜底路径。

**对齐能力是可选 extra（`subtitle-alignment`，faster-whisper + ctranslate2），未装时静默回退机械分配，产物与接入前完全一致。** 模型是百 MB 级的 ASR 小模型、不是大模型，CPU 可跑；解码走随包 ffmpeg（`docs/adr/0095` 同一通道），绕开 faster-whisper 内部与 PyAV 19.x 不兼容的 `av.open(metadata_errors=)`。镜像默认装这个 extra；本地/CI 基础环境不装。

**接入是部署级开关（环境变量 `ARCREEL_SUBTITLE_ALIGNMENT`，默认关）。** 字幕计时策略是技术机制而非创作参数——字幕文本、切句、归属都不变，只改起止时间的来源，没有站得住的按项目差异化需求（对齐缺席或失败一律静默回退机械分配，不需要用户选），部署侧的运维事实（extra 是否安装、模型缓存、CPU 预算）也都在部署层。曾经落地过项目级开关（`project.json` 顶层 `subtitle_alignment`）作为灰度载体（先小项目验证再铺开），验证完成后收归部署级并移除项目字段；存量项目残留的字段值无读者、无害。开着才会改变字幕 basis；存量部署未开时字幕 artifact 不因本次接入而重算。写入路径（`presentation_read_model`）与校验路径（`artifact_planner` 的 frozen 重放与 current 依据）经共用的 `build_aligned_timing` 注入同一策略——frozen 重放用机械时序去比对已存对齐字幕会永远判不一致、每轮激活重写一遍 artifact，这是必须三处一起改的硬约束。

**对齐结果按「音频 content_digest + 句子序列 + 模型 + 语种」缓存到项目 `.arcreel-cache/subtitle-alignment/`。** 对齐是确定性纯计算，缓存让 planner 每次激活的 ASR 成本从「每单元几十秒 CPU」降到零（首次后命中），同时保证生成侧与重放侧算出的 spans 逐字节一致。能力缺席（依赖未装、音频读不出、ASR 失败）不写缓存，下次重试可恢复。

**异步边界：`distribute` 是阻塞 CPU 计算。** 写入路径在 `asyncio.to_thread` 里经 `build_aligned_timing` 预计算 spans，`materialize_speech_presentation` 本身保持纯同步；`AlignedSubtitleTiming.precomputed_spans` 数量与 utterances 不符时忽略预计算值退回现场对齐，任何失败都回退机械分配，流水线不中断。

## 明确不采用

- **供应商合成时返回时间戳**（DashScope realtime 版、Azure/MiniMax）：换实时协议等于重写计费、重试、下载整条链路；qwen3-tts 同步端点不返回时间戳。
- **供应商 ASR 转写（paraformer 等）**：只收公网 URL（配音在本地落盘，要另建上传中转）、异步任务模式、ITN 逆文本正则化让「二零二三」变「2023」需额外文本匹配；且受单一供应商语种覆盖限制。
- **词级对齐模型（WhisperX / MFA）**：字幕 cue 是句子级，按句末停顿找边界即可；句级对齐绕开各语言分词差异（中文无空格、越南语多音节），多语言难度大幅下降。质量优先时可在 `align_sentences` 内换后端，协议不变。
- **只在渲染/导出路径对齐**：planner 的 frozen 重放会判不一致，字幕 artifact 每轮激活重写一遍，永不 settle。
- **默认开启**：一开就让存量项目的字幕 basis 全量从 mechanical 变 aligned，触发一轮全量重生成，且预热 ASR 的 CPU 成本应由部署方知情选择；默认关 + 部署显式开启，先小范围验证再铺开。

## Consequences

- 开启后首次物化每个带音轨的单元（use_tts 的旁白单元、生成了音频的对白剧单元）付一次 ASR（CPU 几十秒，small/int8），之后命中缓存；未开启项目的路径与接入前逐字节一致。
- 生成时对齐缺席（如依赖未装）落机械 basis、重放时能力就绪算对齐 basis 的一侧不一致会自愈：该单元多转一轮重新生成后稳定，反向同理。
- 音频重新生成（content_digest 变）后缓存自然失效，字幕随新配音重算——配音变了字幕该重算，语义正确。
- `basis_identity` 记录模型与语种（`aligned-sentence-forced-alignment`），换对齐模型后产物时效体系自动让字幕草稿重生成。
- 缓存目录 `.arcreel-cache/` 是项目内隐藏目录，不参与 artifact manifest 登记扫描；磁盘写用 mkstemp + os.replace（与 `lib/agent/profile_manifest.py` 同一套路）。
