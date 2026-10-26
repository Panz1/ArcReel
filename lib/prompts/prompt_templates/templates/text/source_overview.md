---
id: text/source_overview
category: text
title: 源文总览
description: 从项目源文提炼项目概述（故事梗概、题材、主题、世界观与源语言），供之后所有生成环节的提示词使用。
stage: source_overview
invoked_by:
  kind: user_action
  name: source_overview
applies_to:
  source_kind:
  - novel
  - screenplay
output_schema: lib.project.project_manager:ProjectOverview
slots:
  source_kind: 源文类型
  target_language: 输出语言，取项目源语言，缺省为中文
  source_content: 项目 source 目录下全部源文拼接的正文
protected: false
---
{{ variant("text/source_overview/task", source_kind) }}

**输出语言**：所有字符串值必须使用 {{ target_language }}；JSON 键名 / 枚举值保持英文。

# 关键场面清单（hook_points）

通读全文，挑出 3-8 个「爆点」场面——最炸裂的冲突、最强悬念、最极致的身份反差、最爽的打脸、最关键的反转——按剧情顺序写入 hook_points。这是给短视频首集「冷开场」备的弹药：观众只给前几秒，开场必须直接落在这些场面之一上。

- **description**：直接入画的具体事件——谁、在哪、发生了什么、结果如何；不写抽象概括（「矛盾激化」不合格，「她在婚礼上当众撕了婚书」合格）。
- **kind**：conflict（直接冲突）/ suspense（强悬念）/ contrast（极致反差）/ face_slap（打脸）/ reversal（反转），五选一。
- **anchor**：该场面所在处的逐字原文片段，10~30 个字符、含标点、从下方原文中原样摘抄——它用于在全文中定位这场戏，必须逐字一致。
- **characters**：场面中的主要角色名，按原文称呼；泛指群演（路人甲、村民若干）不写。
- 宁缺毋滥：只收真正有冲击力的场面；全文确实没有强场面时给空数组，不要硬凑。

{{ source_content }}
