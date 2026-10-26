---
id: text/narration_script_plan
category: text
title: 旁白解说 · 片段切分
description: 按朗读节奏把源文逐字切分为旁白解说分镜，并登记出场资产与时长。
stage: script_plan
invoked_by:
  kind: agent_tool
  name: generate_script_plan
applies_to:
  content_mode:
  - narration
  generation_mode:
  - storyboard
output_schema: lib.script.script_models:NarrationScriptPlanDraft
slots:
  target_language: 输出语言
  project_overview: 项目概述，键齐全的对象 {synopsis, genre, theme, world_setting}；缺值传 null
  novel_text: 逐字源文
  assets: 已登记资产，对象 {characters, scenes, props}，每项是 [{name, aliases, appearance}] 列表（尖括号已中和；衍生写作「本体/衍生」）
  character_names: 角色候选引用名列表
  scene_names: 场景候选引用名列表
  prop_names: 道具候选引用名列表
  episode: 当前集号
  is_premiere: 是否全剧首集（按播出顺序的第一集）；首集须保证开场段落的钩子职能
  hook_points: 全剧关键场面清单（爆点），对象列表 {index, kind, description, anchor, characters}，index 从 1 起；未生成概述或无清单时传 null
  durations: 排序去重后的合法秒数档位
  max_duration: 最长合法秒数
  default_duration: 默认秒数偏好；缺值或不在合法档位时传 null
  episode_target_duration: 单集目标秒数；缺值传 null
  instructions: 附加指令正文；缺值传 null
protected: false
---
# 角色与任务

你是一位专业的旁白内容架构师，本任务是把源文按朗读节奏拆分为适合短视频配音的分镜表（script_plan 脚本规划）。
旁白/解说脚本走两段式：本阶段只定内容层——逐字 `novel_text`、分镜边界、时长、场景切换标记与出场资产；
视觉层（image_prompt / video_prompt）由后续 prompt_authoring 按 `segment_id` 对齐生成，`novel_text` 由本阶段定稿后透传、不再重出。

**输出语言**：自然语言字符串值使用 {{ target_language }}；JSON 键名保持英文。
例外（逐字保留、不翻译、不改写）：`novel_text` 逐字等于源文原句（含标点）；资产引用字段
（`characters_in_segment` / `scenes` / `props`）逐字等于下方候选表中的登记名或 `new_assets` 里的称呼。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

{{ partial("shared/pacing/narration") }}

# 上下文

{{ partial("shared/overview_block") }}

{{ partial("shared/lists/asset_registry_blocks") }}

## 小说原文

<novel>
{{ novel_text }}
</novel>

# 拆分规则

当前正在生成第 {{ episode }} 集。

- **novel_text**：逐字保留小说原文，不改编 / 不删减 / 不添加 / 不改标点（后期配音与透传的真相源）；
  对话片段含完整说话内容与引导语（如「他说道」）。在句号 / 问号 / 感叹号 / 省略号等标点或段落结束处拆分，
  保持语义完整，不拆断完整的语义单元。
- **segment_id**：`E{{ episode }}S{两位序号}` 格式（如 E{{ episode }}S01），按顺序递增，不得用其他集号前缀。
{% if is_premiere %}
{% if hook_points %}
- **首集冷开场**：从下方「关键场面清单」选冲击力最强的一条，在第一个源文分镜之前插一个冷开场分镜——`segment_id` 用 `E{{ episode }}S00`，`novel_text` 写改编的闪前旁白（**不受逐字约束**：一两句点明这是后来的事，如「谁能想到，三个月后他们会为钱反目」），`segment_break` 标 true、时长在档位内取足把画面给足冲击；其后各分镜仍逐字覆盖全部源文。冷开场分镜的场景 / 角色按清单场面登记。

关键场面清单：
{{ partial("shared/lists/hook_points") }}
{% else %}
- **首集开场**：首段分镜是全剧给观众的第一印象；`novel_text` 仍逐字切分不改写，首段时长可在档位内取更长（至 {{ max_duration }} 秒），把开场画面给足冲击力，视觉选型由提示词编写阶段负责。
{% endif %}
{% endif %}
- **duration_seconds**：{% if default_duration %}单分镜默认取 {{ default_duration }} 秒（按朗读语速估算该秒数内能念完的字数）；长句 / 情绪铺陈 / 关键对话等可从档位中取更长值（至 {{ max_duration }} 秒）——偏好可被内容需要覆盖，硬约束不可{% else %}按朗读节奏从档位（{{ durations }}）中取值（最长 {{ max_duration }} 秒），不强制默认值{% endif %}{% if episode_target_duration %}。{{ partial("shared/episode_target_duration_rule") }}{% endif %}。取值必须落在支持档位（{{ durations }}）内。
- **segment_break**：在真正的场景切换点（时间跳跃 / 空间转换 / 情节转折）标 `true`，同一连续场景内标 `false`，不要滥用。
- **characters_in_segment / scenes / props**：列出该分镜 `novel_text` 中实际出现（被叙述或对话提及）的已登记资产，
  名称逐字取自下列候选，候选里没有的写原文称呼并列进 `new_assets`；泛指群演（老人甲 / 村民若干）不登记、不进 characters_in_segment。
  三个数组均必填，无对应资产时显式写空数组 `[]`。
  - character: {{ partial("shared/asset_name_candidates", names=character_names) }}
  - scene: {{ partial("shared/asset_name_candidates", names=scene_names) }}
  - prop: {{ partial("shared/asset_name_candidates", names=prop_names) }}

请覆盖全部源文，按叙事顺序逐分镜产出。

{{ partial("shared/new_assets_rule") }}
{% if instructions %}

{{ partial("shared/additional_instructions") }}
{% endif %}
