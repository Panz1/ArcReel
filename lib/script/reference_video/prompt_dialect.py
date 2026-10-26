"""视频模型的提示词方言：参考素材指代与台词句式的逐模型写法。

参考生视频的最终 prompt 由 ``reference_video/unit`` 模版拼成三段论——主体绑定、单元正文、
风格与负向约束。三段里的**参考素材指代**与**台词句式**并非所有视频模型都通用的语法：

- Seedance（豆包，按 2.5 官方口径）指代写 ``图片 N`` / ``音频 N``，绑定句式 ``图片 N 是 X``，
  台词写 ``台词 (角色): "内容"``，时间戳用整数秒（``0-3 秒``）——2.5 官方明文响应秒级时间戳，
  2.0 不响应、会自行忽略秒数按镜头序号理解（本项目不为 2.0 单设方言，退化无损）；
- 万相 3.0 官方按 ``图N`` / ``音频N`` 指代，绑定句式 ``图N是X``，台词 ``xx说："内容"``，
  多镜头时间码 ``分段N[起-止秒]``，负向约束前缀写 ``Negative:``，口型指令 ``口型同步``；
- MiniMax H3 官方 API 示例写 ``reference images 1 and 2``，前端产品统一用 ``@Image1`` /
  ``@Audio1``，无方括号运镜与 negative 通道。

ArcReel 早先自有一套 ``@图片N`` / ``@音频N`` / ``<X>说 {台词}`` 的记号。它在中转端点与
自有实现上够用，但对按官方格式训练的模型属于陌生语法——参考图绑定不被认领会让角色
一致性直接掉落，台词花括号不被当成引语会让口型与音频错位。故把随模型变化的写法收进
本模块，渲染层按方言拼串；万相 / Seedance 3.0+ 的官方正文全部使用**裸名主体**（无尖括号），
尖括号记号只在 :data:`GENERIC` 与 MiniMax（存量形态）保留。

带默认值的字段默认即 GENERIC 的存量形态：未显式覆盖的方言自动保持旧行为，新增方言
只写与默认不同的字段。

识别的口径与视频通道一致（复用 :func:`lib.backends.video_backends.name_family.capability_names`：
按目录条目的官方模型名与别名比对）。认不得的模型回落 :data:`GENERIC`，输出与本模块引入
**之前逐字一致**——宁可退回通用写法，也不按模型 ID 的子串猜，猜错比不猜更贵。
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.backends.video_backends.name_family import capability_names


@dataclass(frozen=True, slots=True)
class PromptDialect:
    """一套提示词写法。模板字段均为 ``str.format`` 模板，占位符见各字段说明。"""

    #: 方言名，进日志与测试断言用
    name: str
    #: 参考图指代模板，``{n}`` 是图号（从 1 起，与随请求发出的参考图严格同序）
    image_ref: str
    #: 参考音频指代模板，``{n}`` 是音频号（从 1 起）
    audio_ref: str
    #: 台词句式模板，``{subject}`` 是主体名（裸名，不含记号）、``{text}`` 是逐字台词
    speech: str
    #: 负向约束行的前缀；空串表示该方言的负向走正文句式（不带前缀）
    negative_prefix: str
    #: 主体记号模板，``{name}`` 是资产名。GENERIC 用尖括号（历史形态）；万相与 Seedance
    #: 官方正文全是裸名（「叶星辰站在门内偏左」「台词 (机器人): "…"」），尖括号对官方
    #: 训练语料是陌生记号，故这两个方言回落裸名。
    subject_ref: str = "<{name}>"
    #: 主体绑定句式，``{name}`` 是记号化后的主体、``{image}`` 是参考图指代。GENERIC 沿用
    #: 「<X>@图片N」紧邻拼接；万相官方「图1是叶星辰」；Seedance 官方「图片 1 是主角张三」。
    binding: str = "{name}{image}"
    #: 时间码模板，占位 ``{n}``（镜头序号）/ ``{start}`` / ``{end}``（起止秒）。
    #: 万相 3.0 要求「序号 + 起止秒」（``分段N[起-止秒]``，每段 2-5 秒、首尾相接）；
    #: Seedance 2.5 官方明文响应整数秒时间戳（``0-3 秒``）；GENERIC / MiniMax 只留镜头
    #: 序号（Seedance 2.0 与 MiniMax 对秒级硬卡支持不稳，少写不误导）。
    timecode_format: str = "镜头{n}："
    #: 音色声明主干，``{name}`` 是记号化主体、``{audio}`` 是音频指代。Seedance 官方句式
    #: 「图片 1 使用音频 1 音色」需要图号——``voice_line_with_image`` 非空且该 speaker 有
    #: 参考图时优先用它，纯画外角色（无图号）退回本模板。
    voice_line: str = "{name}的台词音色参考 {audio}，只取音色、语速与情绪，台词以正文为准"
    #: 带参考图的音色声明句式（占位 ``{image}`` / ``{audio}``）；空串表示无图号特化。
    voice_line_with_image: str = ""
    #: 主体锁定回述前缀；空串表示该方言不产出主体锁定行——Seedance 官方无此概念，
    #: 其绑定清单行（「图片 N 是 X」逐项列明）已承担同等职责。
    subject_lock_prefix: str = "主体锁定："
    #: 口型同步指令，随声音声明注入（有声且有台词的单元）；空串表示该方言无此指令。
    lip_sync: str = ""
    #: 声明区末尾的正文式负向句（负向「首尾双写」的首）；空串表示不产出。Seedance 官方
    #: BGM badcase 教训：要压住 BGM 需穷举同义词、且约束写在 prompt 开头与结尾各一遍。
    negative_head: str = ""

    def image(self, number: int) -> str:
        """第 ``number`` 张参考图的指代文本。"""
        return self.image_ref.format(n=number)

    def audio(self, number: int) -> str:
        """第 ``number`` 段参考音频的指代文本。"""
        return self.audio_ref.format(n=number)

    def say(self, subject: str, text: str) -> str:
        """一个发声记号的渲染结果：``subject`` 是主体名（不含记号），``text`` 是逐字台词。"""
        return self.speech.format(subject=subject, text=text)

    def subject(self, name: str) -> str:
        """主体记号：正文与声明区里「画面里的这个人 / 物」的写法。"""
        return self.subject_ref.format(name=name)

    def bind(self, name: str, image_no: int) -> str:
        """主体与第 ``image_no`` 张参考图的绑定片段（第一段绑定行的一个项）。"""
        return self.binding.format(name=self.subject(name), image=self.image(image_no))

    def timecode(self, segment_no: int, start: int, end: int) -> str:
        """把一个分镜的起止秒渲染成当前模型认得的时间标记。

        标记里只放序号与起止秒（按 ``timecode_format`` 取用），不重复「画面内容」等
        前缀——正文里若已有描述性前缀，渲染后只会多出一个 ``：``，不影响语义。
        """
        return self.timecode_format.format(n=segment_no, start=start, end=end)

    def transition(self, kind: str = "cut") -> str:
        """镜头间转场指令，写在上一镜头段末。

        万相 3.0 官方在段末写 ``硬切转场`` / ``叠化转场``；其余模型无官方转场 token（硬切
        为默认行为），回落空串，不把认不牢的指令硬塞进去——这也是切换 Seedance / MiniMax
        时不会出语法杂音的原因。

        ``kind`` 取 ``"cut"``（硬切，默认）或 ``"dissolve"``（叠化）；溶解需由正文 / 字段显式给出，
        渲染层目前统一回落硬切。
        """
        if self.name != "wan3":
            return ""
        return "硬切转场" if kind == "cut" else "叠化转场"


#: 方言化之前的原写法。认不得的模型一律用它，保证既有项目的成片与预览不因本模块的存在而改变。
GENERIC = PromptDialect(
    name="generic",
    image_ref="@图片{n}",
    audio_ref="@音频{n}",
    speech="<{subject}>说 {{{text}}}",
    negative_prefix="Avoid:",
)

#: Seedance 系列（豆包），按 2.5 官方口径。指代 ``图片 N`` / ``音频 N``，绑定 ``图片 N 是 X``，
#: 台词 ``台词 (角色): "内容"``，时间码整数秒（2.5 响应；2.0 忽略秒数按镜头序号理解，
#: 不为 2.0 单设方言）。负向无前缀行，走正文句式：官方 BGM badcase 要求穷举同义词并
#: 「首尾各写一遍」，故 ``negative_head`` 在声明区末再写一遍音频 / 字幕类约束。
SEEDANCE = PromptDialect(
    name="seedance",
    image_ref="图片 {n}",
    audio_ref="音频 {n}",
    speech='台词 ({subject}): "{text}"',
    negative_prefix="",
    subject_ref="{name}",
    binding="{image} 是 {name}",
    timecode_format="{start}-{end} 秒：",
    voice_line_with_image="{image} 使用{audio} 音色，只取音色、语速与情绪，台词以正文为准",
    subject_lock_prefix="",
    lip_sync="逐字同步口型",
    negative_head="不要bgm、不要背景音乐、不要配乐、不要音乐、不要旋律。不要字幕。",
)

#: 万相 3.0 系列。指代 ``图N`` / ``音频N``，绑定 ``图N是X``，主体锁定回述与多镜头时间码
#: （``分段N[起-止秒]``）均为官方写法；负向前缀 ``Negative:``；口型指令 ``口型同步``。
WAN30 = PromptDialect(
    name="wan3",
    image_ref="图{n}",
    audio_ref="音频{n}",
    speech='{subject}说："{text}"',
    negative_prefix="Negative:",
    subject_ref="{name}",
    binding="{image}是{name}",
    timecode_format="分段{n}[{start}-{end}秒]：",
    lip_sync="口型同步",
)

#: MiniMax H3（Hailuo 3）的多模态参考。官方 API 示例正文写
#: ``the character's appearance follows reference images 1 and 2``（英文序数 + 编号），
#: 而 H3 的前端产品统一教用户输入 ``@Image1`` / ``@Video1`` / ``@Audio1``，故取更短、
#: 且被广泛接受的 ``@ImageN`` 写法。
#:
#: 与其它两家的关键差别：H3 **原生音频常开**，台词必须写进正文并加引号（口型与语音都由
#: 这一次生成产出），没有独立的台词字段；官方 V2 文档也**不提供方括号运镜指令**，
#: 镜头语言一律用自然语言描述。另注意 ``prompt_optimizer`` 只存在于 legacy Hailuo 接口
#: （默认开启、会改写整段 prompt），本方言不覆盖 legacy 模型。本方言维持尖括号主体与
#: ``Avoid:`` 前缀的存量形态，官方形态的校正见 docs/research/arcreel-video-prompt-dialect-research.md。
MINIMAX_H3 = PromptDialect(
    name="minimax-h3",
    image_ref="@Image{n}",
    audio_ref="@Audio{n}",
    speech='<{subject}>说："{text}"',
    negative_prefix="Avoid:",
)

#: 按名字族认模型：``(子串, 方言)``。顺序即优先级，先命中先用。
#: 只收官方模型名与别名里稳定出现的片段——``wan2.7`` 不含 ``wan3``，不会误认成 3.0；
#: ``MiniMax-Hailuo-2.3`` 不含 ``minimax-h3``，不会被认成 H3。
_DIALECT_MARKERS: tuple[tuple[str, PromptDialect], ...] = (
    ("seedance", SEEDANCE),
    ("minimax-h3", MINIMAX_H3),
    ("wan3", WAN30),
    ("wan-3", WAN30),
)


def dialect_for(model_id: str | None) -> PromptDialect:
    """按模型名取方言；认不得（含 ``None``）时回落 :data:`GENERIC`。

    比对名取自目录条目的官方模型名与别名（同视频通道的能力认定口径），所以自定义供应商写的
    上游模型 ID（如 ``doubao-seedance-2-5-260628``）与内置条目的短名（``doubao-seedance-2.5``）
    都能认出来。
    """
    if not model_id:
        return GENERIC
    for name in capability_names(model_id):
        lowered = name.lower()
        for marker, dialect in _DIALECT_MARKERS:
            if marker in lowered:
                return dialect
    return GENERIC
