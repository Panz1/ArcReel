import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, ChevronRight, X } from "lucide-react";
import { useShallow } from "zustand/react/shallow";

import { OutputTruncationHint } from "@/components/shared/OutputTruncationHint";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { isAdScriptTask } from "@/hooks/useAdScriptEntry";
import { useTasksStore } from "@/stores/tasks-store";
import { outputTruncationOf } from "@/utils/output-truncation";
import { workflowPlanKey, useWorkflowStore } from "@/stores/workflow-store";
import type { TaskItem } from "@/types";
import type { WorkflowDraft } from "@/types/workflow";

import { latestEpisodeTextTaskFailure, type EpisodeTextTaskKind } from "./text-task-failure";

const FAILURE_KEYS: Record<EpisodeTextTaskKind, string> = {
  text_script_plan: "script_plan_failed",
  text_episode_script: "prompt_authoring_failed",
  text_draft_repair: "draft_repair_failed",
};

/**
 * 用户已「已读」的纯错误类失败提示：按 `task_id` 持久化，跨刷新 / 切集 / 重进集页都不应再弹。
 * 注意：仅适用于「从未产出待修复草稿」的纯错误（模型超时、能力缺失等）——这类问题无状态可变，
 * 关闭即视为已知。草稿类失败（违约落草稿、AI 修复失败）不做持久化关闭：问题状态可变，关闭只清静
 * 当前挂载，重进后重新评估，草稿还 `needs_repair` 就重新提醒（真有问题才提示）。
 */
const DISMISSED_KEY = "arcreel:dismissed-text-task-failures";
const MAX_DISMISSED = 100;

function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISSED_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function saveDismissed(ids: Set<string>): void {
  try {
    const entries = [...ids].slice(-MAX_DISMISSED);
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(entries));
  } catch {
    // localStorage 不可用时退化为仅当次会话隐藏（useState 已兜底）。
  }
}

/**
 * 失败的文本任务对应的草稿种类：违约失败会落一份「待修复草稿」，草稿在场才是真问题；草稿已晋升 /
 * 丢弃（`content.drafts` 不再有该种类或不再 `needs_repair`）即视为已解决，不再提示。
 */
const PROMPT_AUTHORING_DRAFT_KIND = "reference_video_prompt_authoring";
const SCRIPT_PLAN_DRAFT_KINDS = new Set(["script_plan", "drama_script_plan", "narration_script_plan"]);
// 草稿端点 `doc_type` → 状态草稿种类（见 step-list 的 `DOC_TYPE_BY_DRAFT_KIND` 反查）。
const DOC_TYPE_TO_DRAFT_KIND: Record<string, string> = {
  reference_prompt_authoring: PROMPT_AUTHORING_DRAFT_KIND,
  drama_script_plan: "drama_script_plan",
  narration_script_plan: "narration_script_plan",
  reference_script_plan: "script_plan",
};

function draftKindsForFailure(task: TaskItem): Set<string> {
  if (task.task_type === "text_episode_script") return new Set([PROMPT_AUTHORING_DRAFT_KIND]);
  if (task.task_type === "text_script_plan") return new Set(SCRIPT_PLAN_DRAFT_KINDS);
  if (task.task_type === "text_draft_repair") {
    // 修复任务的 resource_id 形如 `episode-{N}-{doc_type}`。
    const docType = task.resource_id.split("-").slice(2).join("-");
    const kind = DOC_TYPE_TO_DRAFT_KIND[docType];
    return kind ? new Set([kind]) : new Set();
  }
  return new Set();
}

/** 该失败是否产生了一份待修复草稿（而非纯错误）。后端 `render_report` 的报告原文固定带「待修复草稿」。 */
function producedDraft(task: TaskItem): boolean {
  return (
    task.task_type === "text_draft_repair" ||
    (task.error_message?.includes("待修复草稿") ?? false)
  );
}

function outstandingDraft(drafts: WorkflowDraft[] | null | undefined, kinds: Set<string>): boolean {
  if (!drafts) return false;
  return drafts.some((d) => kinds.has(d.kind) && d.needs_repair);
}

/**
 * 本集最近一次文本任务（AI 规划脚本、编写提示词、AI 修复、广告/短片 AI 生成脚本）失败时的原因与出路，
 * 挂在集页顶部，内容确认页、时间线与集原文页都看得到。
 *
 * 提示的显隐是状态驱动的：
 * - 违约失败落下的待修复草稿仍 `needs_repair` → 真问题还在，提示；手动关闭只清静本次挂载，
 *   刷新 / 切集 / 重进集页后重新评估，草稿还在就重新提醒（关闭不等于问题已解决）。
 * - 那份草稿已晋升 / 丢弃 → 问题已解决，自动消失（无需手动关闭）。
 * - 纯错误（模型超时、能力缺失等从未产生草稿）→ 没有可解的草稿，照常提示；关闭后置为「已读」
 *   并持久化，刷新 / 切集 / 重进集页不再弹，直到下一次失败。
 *
 * 摘要只显示后端按界面语言渲染的原因；问题码、参数与服务端原文收进可展开的「详情」。后端没能把原因
 * 本地化时（外部或未知错误）不带原文字段，原文本身就是摘要，也就没有详情。
 */
export function TextTaskFailureNote({
  projectName,
  episode,
  isAd = false,
  hasScript = true,
}: {
  projectName: string;
  episode: number;
  isAd?: boolean;
  hasScript?: boolean;
}) {
  const { t } = useTranslation(["dashboard", "common"]);
  const failure = useTasksStore(useShallow((s) => latestEpisodeTextTaskFailure(s.tasks, projectName, episode)));
  // 本集的工作流内容（含草稿列表）：计划尚未刷到本集或还在加载时为 null，此时保守沿用现状、不草率隐藏。
  const content = useWorkflowStore((s) =>
    s.planKey === workflowPlanKey(projectName, episode) ? (s.plan?.status?.content ?? null) : null,
  );
  const [dismissed, setDismissed] = useState<Set<string>>(loadDismissed);
  const [sessionDismissed, setSessionDismissed] = useState<string | null>(null);

  if (failure === null) return null;
  const task = failure.task;
  // 该失败是否产生了一份待修复草稿（草稿类失败，状态可变）；纯错误为 false。
  const kinds = draftKindsForFailure(task);
  const isDraftFailure = kinds.size > 0 && producedDraft(task);
  const isDismissed = dismissed.has(task.task_id) || sessionDismissed === task.task_id;

  // 状态驱动：产生过待修复草稿的失败，其草稿已晋升 / 丢弃 → 问题已解决，不再提示。
  const draftResolved = content !== null && isDraftFailure && !outstandingDraft(content.drafts, kinds);

  if (isDismissed || draftResolved) return null;

  const truncation = outputTruncationOf(task);
  const reason = task.error_message ?? t("script_plan_failed_unknown");
  const adScript =
    failure.kind === "text_episode_script" && isAd && (!hasScript || isAdScriptTask(task));
  return (
    <div
      role="alert"
      className="mx-4 mt-2 flex items-start gap-2.5 rounded-xl border border-destructive/35 px-4 py-2.5 text-sm"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
        <p className="m-0 text-destructive">{t(adScript ? "ad_script_failed" : FAILURE_KEYS[failure.kind], { reason })}</p>
        {truncation ? <OutputTruncationHint truncation={truncation} /> : null}
        {task.error_detail ? (
          <Collapsible render={<div className="flex w-full min-w-0 flex-col gap-1" />}>
            <CollapsibleTrigger render={<Button variant="ghost" size="xs" />}>
              {t("text_task_failure_details")}
              <ChevronRight
                data-icon="inline-end"
                aria-hidden
                className="transition-transform group-aria-expanded/button:rotate-90"
              />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs text-subtle-foreground">
                <dt className="text-muted-foreground">{t("text_task_failure_code")}</dt>
                <dd className="m-0 min-w-0 font-mono break-all">{task.error_code}</dd>
                <dt className="text-muted-foreground">{t("text_task_failure_params")}</dt>
                <dd className="m-0 min-w-0 font-mono break-all">{paramsText(task.error_params)}</dd>
                <dt className="text-muted-foreground">{t("text_task_failure_server_text")}</dt>
                <dd className="m-0 min-w-0 font-mono break-all whitespace-pre-wrap">{task.error_detail}</dd>
              </dl>
            </CollapsibleContent>
          </Collapsible>
        ) : null}
      </div>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label={t("common:close")}
        onClick={() => {
          // 草稿类失败只静音当前挂载（问题状态可变，重进后重新评估）；纯错误才持久化为「已读」。
          setSessionDismissed(task.task_id);
          if (!isDraftFailure) {
            const next = new Set(dismissed);
            next.add(task.task_id);
            setDismissed(next);
            saveDismissed(next);
          }
        }}
      >
        <X aria-hidden />
      </Button>
    </div>
  );
}

function paramsText(params: Record<string, unknown> | undefined): string {
  return Object.entries(params ?? {})
    .map(([key, value]) => `${key}=${typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}`)
    .join(", ");
}
