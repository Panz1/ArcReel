---
id: text/drama_script_plan
category: text
title: 剧情演绎脚本规划
description: 把本集源文拆为剧情演绎的结构化分镜内容：分镜边界、出场资产、画面描述、逐字口播与原文锚。
stage: script_plan
invoked_by:
  kind: agent_tool
  name: generate_script_plan
applies_to:
  content_mode:
  - drama
  generation_mode:
  - storyboard
  source_kind:
  - novel
  - screenplay
output_schema: lib.script.script_models:DramaNormalizedScript
slots:
  source_kind: 源文类型
  target_language: 输出语言，取项目源语言
  project_overview: 项目概述，键齐全的对象 {synopsis, genre, theme, world_setting}；缺值传 null
  style: 项目画风
  assets: 已登记资产，对象 {characters, scenes, props}，每项是 [{name, aliases, appearance}] 列表（尖括号已中和；衍生写作「本体/衍生」）
  character_names: 可引用的角色名，衍生写作「本体/衍生」
  scene_names: 可引用的场景名
  prop_names: 可引用的道具名
  novel_text: 本集源文
  episode: 集号
  is_premiere: 是否全剧首集（按播出顺序的第一集）；首集须套用开场钩子规则
  durations: 视频模型支持的秒数档位
  max_duration: 最长档位秒数
  default_duration: 单个分镜的默认秒数；未设置为空
  speech_rate: 口播语速（每秒阅读单位数）
  speech_unit: 阅读单位量词（字或词）
  episode_target_duration: 单集目标时长秒数；未设置为空
  episode_outline: 本集大纲（title、story_beats、hook、next_episode_teaser）；未规划为空
  next_episode_outline: 下集大纲，形状同本集大纲；未规划为空
  instructions: 附加指令；未提供为空
protected: false
---
{{ variant("text/drama_script_plan/task", source_kind) }}

**输出语言**：自然语言字符串值必须使用 {{ target_language }}；JSON 键名 / 枚举值保持英文。{{ variant("text/drama_script_plan/language_rule", source_kind) }}
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

{{ partial("shared/pacing/drama") }}
{% if is_premiere %}
{{ partial("shared/premiere_opening") }}
{% endif %}

## 项目信息

<overview>
{{ project_overview.synopsis or "" }}

题材类型：{{ project_overview.genre or "" }}
核心主题：{{ project_overview.theme or "" }}
世界观设定：{{ project_overview.world_setting or "" }}
</overview>

<style>
{{ style }}
</style>

{{ partial("shared/lists/asset_registry_blocks") }}

## 源文

<{{ source_kind }}>
{{ novel_text }}
</{{ source_kind }}>

{% if episode_outline %}
<episode_outline>
本集大纲（分集规划已定，剧本必须严格按此创作，不得偏离）：
{% if episode_outline.title %}
本集标题：{{ episode_outline.title }}
{% endif %}
{{ partial("shared/lists/episode_outline_lines", outline=episode_outline) }}

严格按本集大纲创作（遵循已定的分集边界与节点）：
- 边界锁定：novel_text 即为本集按 end_anchor 切定的原文范围，剧本只改编此范围内的内容；不得外扩到相邻集的情节，也不得自行新增原文范围之外的主要事件。
- 节点全覆盖：大纲里的每条「故事节点」都必须对应至少一个分镜，分镜的情节推进顺序须与故事节点一致，不得遗漏任何一条；允许一条节点拆成多个分镜，但不得把节点之外、原文范围之外的额外主线塞进本集。
{% if episode_outline.hook or episode_outline.next_episode_teaser %}

- 钩子定格结尾：本集「集尾钩子」描述的悬念 / 未完成动作 / 反转，必须在结尾的分镜实际演出来并定格在画面；有下集预告语时只用于设计结尾衔接，用结尾画面或对白自然引出，不要生硬插入「下集预告」字样的旁白，也不得提前把下集情节写进本集。
{% if is_premiere %}

- 首集冷开场：大纲第一个故事节点若是「冷开场」节拍（含「闪前」借用后面集的场面），第一个分镜必须实际演出该场面，不得只在画面描述里带过；闪前场面不在本集源文区间内时，该分镜的 source_text 留空，并用一句画外音点明这是后来的事（如「此时谁也没想到，……」），随后再按顺序回补前因。除冷开场节拍外，其余内容仍受上方「边界锁定」约束。
{% endif %}
{% endif %}
</episode_outline>

{% endif %}
{% if next_episode_outline %}
<next_episode_outline>
下集大纲（仅用于设计本集结尾的衔接，不要把下集情节提前写进本集）：
{% if next_episode_outline.title %}
下集标题：{{ next_episode_outline.title }}
{% endif %}
{{ partial("shared/lists/episode_outline_lines", outline=next_episode_outline) }}
</next_episode_outline>

{% endif %}
# 字段写作指引

把源文拆为有序分镜，逐条产出结构化分镜内容。当前正在生成第 {{ episode }} 集。

## 基础字段

- **scene_id**：`E{{ episode }}S{两位序号}` 格式（如 E{{ episode }}S01），按分镜顺序递增，不得用其他集号前缀。
- **duration_seconds**：
  - 档位：{% if default_duration %}从支持的秒数档位（{{ durations }}）中按画面内容选择：默认 {{ default_duration }} 秒，打斗 / 大场面 / 情绪铺陈等画面可取更长档至 {{ max_duration }} 秒，不要默认选最短档{% else %}从支持的秒数档位（{{ durations }}）中按画面内容复杂度匹配合适时长（最长 {{ max_duration }} 秒），不强制默认值{% endif %}。
  - 口播下界：先估算该场 utterances（台词 + 画外音）念完约需的秒数（口播语速约 {{ speech_rate }} {{ speech_unit }}/秒），在上述档位里取**不低于**这个秒数的最接近档位。这是单向下界，画面 / 情绪留白可在此之上取更长档位；utterances 为空的分镜没有此下界；若口播估算已超过最长 {{ max_duration }} 秒，取最长档即可，不删减台词。
{% if episode_target_duration %}
  - 单集目标：{{ partial("shared/episode_target_duration_rule") }}。
{% endif %}
- **segment_break**：{{ variant("text/drama_script_plan/break_rule", source_kind) }}
- **characters_in_scene** / **scenes** / **props**：从下列候选中列出此分镜实际出现的资产。
  - 候选 characters：[{{ character_names | join(", ") or "（暂无）" }}]
  - 候选 scenes：[{{ scene_names | join(", ") or "（暂无）" }}]
  - 候选 props：[{{ prop_names | join(", ") or "（暂无）" }}]
  - 候选里没有的资产写原文称呼，并列进 `new_assets`（见下文）；泛指群演（如「老人甲」「村民若干」）不进 characters_in_scene。
  - **必填约束**：每个分镜的 `scenes` 至少列出一个场景（纯环境空镜也要写它所在的场景）；画面里出现的人物必须全部写进 `characters_in_scene`，不得漏掉主体角色。漏场景会让该分镜在成片里失去空间锚点，漏角色会失去角色一致性。
- **scene_description**：{{ variant("text/drama_script_plan/scene_rule", source_kind) }}

## 逐字内容（内容真相源，定稿后原样保留、不再改写）

- **source_text**：逐字摘录本分镜对应的原文片段，尽量与原文一致、宁缺毋造（无把握可留空）。
- **utterances**：{{ variant("text/drama_script_plan/utterances_rule", source_kind) }}

每个分镜应为一个独立的视觉画面、可在指定时长内完成；避免在一个分镜内安排多个动作或画面切换。

{{ partial("shared/new_assets_rule") }}
{% if instructions %}

{{ partial("shared/additional_instructions") }}
{% endif %}
