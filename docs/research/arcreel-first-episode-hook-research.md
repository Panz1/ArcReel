# 漫剧/短剧第一集开场钩子调研（前 5 秒留人）

> 用途：为分集规划（episode_plan）与各创作类型的剧本规划/提示词编写 prompt 提供「第一集（及单集）开场钩子」的打法依据，回答「前 5 秒怎么抓住观众」。调研日期：2026-10-25。
> 方法：公开行业拆解文 + 平台方法论交叉核实（知乎、人人都是产品经理、南方都市报、网易、36kr、GitHub 开源剧本规范等）；广告侧「黄金 3 秒」的官方数据已在此前 `arcreel-ad-section-timing-research.md` 中核实，本文直接引用。
> 注意：本调研产出的数字（3 秒 / 10 秒 / 30 秒等）是行业经验口径而非平台官方标准，进 prompt 时作为节奏约束使用，不承诺效果数值。

## 一、时间轴公式：单集各秒段做什么

多来源交叉后高度一致的单集骨架（90 秒～3 分钟剧通用，按时长缩放）：

| 时间段 | 必须发生什么 | 依据 |
|---|---|---|
| **0-3 秒** | 开场钩子：直接上冲突/悬念/反差，**零铺垫**；超 50% 用户在前 3 秒决定划走 | 蝉妈妈（经 ad 调研文档核实）；[网易·单集万能节奏公式](https://www.163.com/dy/article/L30RCS1005340TH8.html) |
| **0-10 秒** | 讲清三件事：本集核心矛盾、人物关系、主角当下目标——**不解释前因后果** | 网易·单集公式 |
| **前 30 秒** | 第一次反转或爽点，形成「压抑—爆发」交替 | 网易·单集公式 |
| **每 20-30 秒** | 一处情绪节点（台词冲突 / 动作冲突 / 信息曝光） | 网约·单集公式 |
| **结尾 5-10 秒** | 卡在情绪最高点戛然而止，钩子力度须大于本集所有冲突 | 网易·单集公式 |

同构公式旁证：「3 秒颠覆钩子 + 15 秒情绪积累 + 25 秒核心反转 + 30 秒互动升华」（[腾讯云·0 成本 AI 短剧脚本公式](https://cloud.tencent.com)）；TikTok 官方「63% 高 CTR 视频前 3 秒亮出核心信息」「前 6 秒承载 90% 记忆效果」（见 `arcreel-ad-section-timing-research.md` 表 #1/#2）。

**致命坑**（网易·单集公式 + [人人都是产品经理·情绪印钞机](https://www.woshipm.com/share/6191708.html)）：

1. **开场铺垫超过 10 秒**——大段环境、心理描写，观众直接划走，前期流量全部流失（弃剧主因）；
2. 结尾没有钩子、平缓收尾；
3. 长时间持续虐主角无反击缓冲，观众压抑弃剧。

## 二、开场钩子类型清单（可直接进 prompt 的手法库）

**开场三类**（网易·单集公式）：

| 类型 | 手法 | 例 |
|---|---|---|
| 直接冲突型 | 当众打脸、背叛、对峙 | 离婚协议甩脸、当众扇耳光 |
| 强悬念型 | 危机物件/异常事件入画 | 枪口对准主角、DNA 化验单掉落、神秘来电 |
| 极致反差型 | 身份/处境瞬间颠覆 | 婚礼撕破脸、豪门太太瞬间变弃妇 |

**通用钩子五型**（[GitHub·short-drama 剧本规范](https://github.com/0xsline/short-drama)）：悬念钩、反转钩、情绪钩、信息钩、危机钩。

**第一集专用：「极致冲突前置法」**（[知乎·爆款短剧剧本创作规范](https://zhuanlan.zhihu.com/p/2059299897367597445)）：开篇钩子（第 1 集开头）必须把**全剧最炸的反转、最虐的场面、最爽的打脸放在开场**——即 in medias res / 高潮前置，先炸再回补前因。

**打脸蓄力原则**（[DramaForge](https://dramaforge.cc)）：打脸不是主角突然赢，而是**先让观众清楚看到主角被谁低估、被谁压迫——压迫越具体，反击越有爽感**。开场先立「具体可见的压迫」，再给反击。

**听花岛拆解上百部爆款的结论**（[知乎·短剧编剧黄金手册](https://zhuanlan.zhihu.com/p/2000551987486418463)）：「强情绪冲突 + 悬念感」是留存最佳武器；开场即男主被掌掴、女主下跪、反派嘲讽等强冲突画面。

## 三、漫剧特有规律

- **三段式框架**：南方都市报统计 100 部在榜漫剧，**九成以上遵循「压抑铺垫 → 获得金手指/身份转折 → 反杀打脸」**，开篇主角均陷入压抑处境（[南方都市报](https://m.mp.oeeee.com/a/BAAFRD0000202604271568420.html)）。
- **高频词**：意外、穿越、逆袭、守护、系统、阴谋——共同指向「主角因意外获得转机」（同上）。
- **漫剧与真人短剧节奏骨架一致**，只按时长缩放段落（网易·单集公式，文中明确二者并列处理）。
- **分集节奏**：第 1 集 3 秒抓眼、10 秒出核心冲突、**前 5 集完成第一次打脸逆袭**（[腾讯云 SkillHub·AI 漫剧生成助手](https://skillhub.cloud.tencent.com/skills/user_6ee151b1/ai-comic-auto-creator)）；第 3 集安排一次小爆点、三集一小反转、五集一大高潮（网易·单集公式）。
- 音效/情绪催化剂：耳光声 + 玻璃碎裂等音效桥段自述完播率提升 172%（[人人都是产品经理](https://www.woshipm.com/share/6191708.html)，自述口径，仅作旁证）。

## 四、ArcReel 现状盘点（gap 分析）

| 位置 | 现状 | gap |
|---|---|---|
| `templates/text/episode_plan.md` | 已有钩子感知切分：切点落在剧情弧收束处、首集以最强钩子收尾 | 钩子只管**集尾**；首集**开场**如何设计无任何指令；story_beats 默认按叙事顺序，无冷开场概念 |
| `partials/shared/pacing/drama.md` / `narration.md` | 「开篇 ~4 秒承担钩子职能」一句话 | 无秒段拆解、无手法库、不分第一集/常规集、narration 版无画面要求细则 |
| `templates/text/drama_script_plan.md` | 严格遵循本集大纲（边界锁定 + 节点全覆盖）；钩子定格结尾 | 开场无规则；边界锁定禁止外扩相邻集，与「全剧最炸前置」存在张力（见 §5-D3） |
| `templates/text/reference_video_script_plan.md` | 已有「集首 30 秒」硬约束（0-3s 异常/对抗、3s 人话、3-15s 两个钩子、15-25s 最强冲突、25-30s 翻转） | 不分第一集/常规集；无手法库、无打脸蓄力 |
| `templates/text/narration_script_plan.md` | novel_text 逐字保留、按叙事顺序 | 内容层不可改编——开场钩子只能靠**分集切点 + 视觉层**实现（见 §5-D5） |
| 广告模板 `ad_pacing/tier/*.md` | hook 段 0-3 秒已配比 | 无 gap（人设剧不适用广告框架） |
| 数据结构 | 账本 outline 仅 `hook`（集尾钩子）一个钩子字段 | 无开场钩子字段；v1 不加 schema，靠 story_beats[0] 承载（见 §5-D3） |

## 五、设计：接入方案（v1，prompt-only，不动 schema）

设计原则：**开场钩子在分集规划时设计、在剧本规划时执行**——沿用现有「剧本严格遵循本集大纲」架构，不新增平行机制；第一集判定用**播出顺序第一**（重规划后集号不复用，`episode == 1` 不可靠），由 `script_generator` 从 `project_json` 的 `episodes[]` 顺序计算新 slot `is_premiere` 注入。

### D1 · 新增首集冷开场 partial：`partials/shared/premiere_opening.md`

各创作模式共用（drama / narration 两态由引用处拼装），内容即 §一/§二 的可执行化：

- **0-3 秒**：第一个分镜/首段画面直接是最强冲击瞬间——冲突爆发、危机物件、身份反差三选一；禁止介绍性远景、风景空镜、环境铺陈、字幕开场。
- **3-10 秒**：用一句人对人的话（drama）或一句旁白（narration）点出核心矛盾与主角处境；不解释世界观、不交代前史。
- **手法菜单**（模型按源文内容选型，不硬编）：直接冲突 / 强悬念 / 极致反差；闪前冷开场后再回补前因（drama novel 可用）。
- **打脸蓄力**：开场先立「具体可见的压迫」（谁、以什么方式、当着谁的面压主角），为后续反击蓄力——压迫越具体反击越爽。
- **视觉层**（prompt_authoring 引用时生效）：首分镜 shot_type 取 Close-up / Extreme Close-up，构图给冲突主体，不做全景交代。

注入点（实施后口径，均 `{% if is_premiere %}`）：
`drama_script_plan.md` 与 `drama_prompt_authoring.md` 引用整个 partial；
`narration_script_plan.md` 用一小节（novel_text 逐字锁定，只放宽首段时长并把视觉冲击交给后续阶段）、
`narration_prompt_authoring.md` 用两行内联块（画面选原文首句可承载的最强视觉）——narration 内容层不可改编，整段 partial 的手法菜单对它半数不可执行，故不整体引用；
`reference_video_script_plan.md` 在集首 30 秒条款下追加首集变体行、`reference_video_prompt_authoring.md` 对 unit 1 追加景别构图要求（见 D4），也不整体引用。

### D2 · 升级常规集开篇规则：`partials/shared/pacing/drama.md` / `narration.md`

把「开篇 ~4 秒承担钩子职能」一句话扩成秒段规则（常规集口径，弱于首集）：0-3 秒以本集最强冲突/悬念画面切入、避免铺垫；3-10 秒接住矛盾。保持文件短小，细节留给 premiere partial。

### D3 · 分集规划产出首集开场设计（关键改动）

`episode_plan.md` 切分规则追加首集条款：

- 首集 hook 说明补一句「本集前 3 秒如何开场」（选型 + 素材来自本集区间内哪个场面）。
- drama（novel）`outline_rule` 追加：**首集 story_beats[0] 允许为「冷开场」节拍**——把本集区间内最炸的冲突场面提到开场演绎，再回补前因；该节拍必须仍取自本集 end_anchor 界定的原文区间（不违反边界锁定，跨集闪前留作 v2 开放问题，见 §六）。
- 首集体量：首集建议取目标体量的下限（宁短勿长，快速进冲突、快速到钩子）。

配套：`drama_script_plan.md` 的 episode_outline 区块在 `is_premiere` 时加一行「story_beats[0] 若为冷开场，第一个分镜必须实际演出来，不得只写画面描述带过」。

### D4 · reference_video 集首 30 秒补首集变体

`reference_video_script_plan.md:109` 集首 30 秒条款追加：首集（`is_premiere`）0-3 秒从「本剧最强冲击场面」中选（含闪前冷开场，正文书写自由度比 storyboard 模式高），并叠加打脸蓄力要求。`reference_video_prompt_authoring.md` 首单元视觉同 D1 视觉层。

### D5 · narration 模式的边界内实现

内容层逐字锁定，开场钩子只能走三条路，写进对应模板：

1. **分集切点**（D3 已覆盖）：首集切得短、从冲突密度最高的段落起收束；
2. **视觉层**：`narration_prompt_authoring` 首分镜画面选原文首句可承载的最强视觉（人物特写/冲突瞬间/异常物件），禁止配「介绍性远景」；
3. 不改写 novel_text（维持逐字真相源不变）。

drama（screenplay 源）：台词与画外音照用作者原文，同样只做 D3 切点 + D1 视觉层强调，不要求作者原文之外的冷开场。

### D6 · 实施清单（已实施，2026-10-25）

| 改动 | 文件 | 状态 |
|---|---|---|
| 新增 partial | `partials/shared/premiere_opening.md` | ✅ |
| 升级 partial | `partials/shared/pacing/drama.md`、`narration.md`（秒段规则扩写） | ✅ |
| 模板注入 | `text/drama_script_plan.md`、`text/narration_script_plan.md`、`text/drama_prompt_authoring.md`、`text/narration_prompt_authoring.md`、`text/reference_video_script_plan.md`、`text/reference_video_prompt_authoring.md`（`is_premiere` 槽） | ✅ |
| 首集条款 | `text/episode_plan.md`（`context_entries` 为空时注入）、`partials/text/episode_plan/outline_rule/drama/novel.md`（冷开场节拍） | ✅ |
| 代码 | `lib/prompts/prompt_builders_script.py` / `prompt_builders_reference.py` 六个构建器加 `is_premiere` 形参；`server/text_generation.py` 三处 script_plan 调用点与 `lib/script/script_generator.py` 三处 prompt_authoring 调用点经 `episode_position(project, episode) == 1` 计算（重规划后集 ID 不复用，不能判 `episode == 1`） | ✅ |
| 测试 | `tests/unit/lib/prompts/test_prompt_builders_script.py`、`test_prompt_builders_reference.py` 补两态断言；`tests/integration/lib/episode/test_episode_planner.py` 期望函数同步本次条款与 acd99c29 漏同步的钩子感知切分行（修复其已红的首集分支断言） | ✅ |

## 六、开放问题（v2 已收敛，见 §七）

1. ~~**跨集闪前冷开场**~~：已实施——爆点清单走概述管道（方案 B），首集冷开场允许借用全剧任意位置的场面；「正片删除重复演绎」经决策不做（重复几秒可接受），正片照常演出。
2. **outline 增加 `opening_hook` 字段**：维持不改 schema 的决策——冷开场设计由 story_beats[0]（标注「冷开场（闪前，清单第 N 条）」）+ hook 说明（「开场选用清单第 N 条」）承载；Web 端要展示/编辑时再升级。
3. **首集 A/B**：暂缓，未变。

## 七、v2 实施：爆点扫描 → 存储 → 首集冷开场取材（2026-10-25）

v1 的区间内前置在「首集区间内没有爆点」时无米下锅（创作者确认：全剧爆点应基于完整剧本找、重复演绎几秒可接受、该加旁白加旁白）。v2 把「找爆点」前移到唯一读过全文的环节，冷开场从全剧取材：

**产出与存储**：`ProjectOverview` 新增 `hook_points`（`HookPoint`：description 可入画事件 / kind 五型枚举 conflict·suspense·contrast·face_slap·reversal / anchor 逐字定位片段 / characters），随「生成概述」一次调用产出，落 project.json overview；`filter_hook_points` 剔除锚点对不上原文的坏条目（与参考生视频原文锚同一空白不计口径）。未跑概述 / 清单为空的项目自动退回 v1 区间内前置，不做准入拦截。

**分集规划消费**：`episode_plan` 首批（`context_entries` 为空）且清单非空时，首集条款改为「从清单选冲击力最强的一条作冷开场，允许不在首集区间内（闪前），hook 说明写明选用第 N 条」；drama novel 的大纲规则同步：story_beats[0] 标注「冷开场（闪前，清单第 N 条）」并写全场面内容，其余节点仍在 end_anchor 区间内。

**剧本规划消费**（首集，`is_premiere` 沿用 v1 判定）：
- drama（storyboard）：冷开场分镜实际演出闪前场面，source_text 留空（本就允许）、加一句画外音点明「这是后来的事」，边界锁定对冷开场节拍显式豁免；
- reference_video：unit 1 演出冷开场并标 `cold_open=true`、source_text 留空——schema 放开空锚，`collect_reference_flat_violations` 对 cold_open unit 跳过 `validate_source_text_anchor`（普通 unit 空锚/假锚照旧拦截）；正片重复演绎不做去重；
- narration：冷开场分镜 `E{集}S00`，novel_text 写改编闪前旁白（单分镜逐字豁免，prompt 层），其后的分镜仍逐字覆盖全部源文。

**边界**：screenplay（成品剧本）源暂不放开（沿用区间内前置）；爆点清单暂无 Web 编辑入口（prompt 消费为主）；清单对中段反转集 / 季终钩子的复用留作后续。

## 来源总表

- [网易 · 拆解 100+ 部爆款短剧/漫剧后，摸清单集万能节奏公式](https://www.163.com/dy/article/L30RCS1005340TH8.html)（2026-07，本文主要骨架）
- [知乎 · 爆款短剧剧本创作规范](https://zhuanlan.zhihu.com/p/2059299897367597445)（三类钩子、极致冲突前置法）
- [知乎 · 短剧编剧黄金手册：按秒拆解爆款](https://zhuanlan.zhihu.com/p/2000551987486418463)（2026-01，听花岛拆解结论）
- [人人都是产品经理 · 情绪印钞机：短剧爆款方法论](https://www.woshipm.com/share/6191708.html)（前 3 秒冲突锚定、音效催化）
- [南方都市报 · AI 漫剧为何越刷越像](https://m.mp.oeeee.com/a/BAAFRD0000202604271568420.html)（2026-04，100 部在榜漫剧统计）
- [腾讯云 SkillHub · AI 漫剧生成助手](https://skillhub.cloud.tencent.com/skills/user_6ee151b1/ai-comic-auto-creator)（第 1 集 3 秒抓眼、前 5 集打脸）
- [GitHub · 0xsline/short-drama](https://github.com/0xsline/short-drama)（钩子五型、节奏曲线）
- [DramaForge](https://dramaforge.cc)（打脸 = 压迫具体化）
- [36kr · AI 漫剧市场规模](https://m.36kr.com/p/3639018845817992)、[21 经济 · 爆款率 0.16%](https://www.21jingji.com/article/20260517/herald/1a483d2c4b1f0622a50b4554d9531199.html)（行业背景）
- 仓库内：`arcreel-ad-section-timing-research.md`（TikTok 前 3 秒官方数据、蝉妈妈黄金 3 秒）
