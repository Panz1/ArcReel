import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";

import { useTasksStore } from "@/stores/tasks-store";
import { useWorkflowStore } from "@/stores/workflow-store";
import { makeTask } from "@/test/factories";
import type { TaskItem } from "@/types";
import type { WorkflowDraft, WorkflowPlan } from "@/types/workflow";

import { TextTaskFailureNote } from "./TextTaskFailureNote";

/** 与组件内 `DISMISSED_KEY` 保持一致；测试直接读写 localStorage。 */
const DISMISSED_KEY = "arcreel:dismissed-text-task-failures";

const TRUNCATED = "文本模型 my-llm 的输出超出了最大输出长度，内容不完整";

function failed(overrides: Partial<TaskItem>): TaskItem {
  return makeTask({ project_name: "demo", status: "failed", queued_at: "2026-10-01T10:00:00Z", ...overrides });
}

function truncated(overrides: Partial<TaskItem>, custom: boolean): TaskItem {
  return failed({
    error_message: TRUNCATED,
    error_code: "text_output_truncated",
    error_params: { provider_id: custom ? "custom-7" : "gemini-aistudio", model: "my-llm", custom_model: custom },
    ...overrides,
  });
}

function renderNote(episode = 1, ad?: { hasScript: boolean }) {
  const location = memoryLocation({ path: "/episodes/1", record: true });
  render(
    <Router hook={location.hook} searchHook={location.searchHook}>
      <TextTaskFailureNote projectName="demo" episode={episode} isAd={ad !== undefined} hasScript={ad?.hasScript ?? true} />
    </Router>,
  );
  return location;
}

describe("TextTaskFailureNote", () => {
  beforeEach(() => {
    useTasksStore.setState(useTasksStore.getInitialState(), true);
    useWorkflowStore.setState(useWorkflowStore.getInitialState(), true);
    localStorage.clear();
  });

  it.each([
    ["text_narration_script_plan", "episode-1", "上一次 AI 规划脚本失败"],
    ["text_episode_script", "episode-1", "上一次编写提示词失败"],
    ["text_draft_repair", "episode-1-narration_script_plan", "上一次 AI 修复失败"],
  ])("sends a truncated custom model of %s to its entry in settings", (taskType, resourceId, lead) => {
    useTasksStore.setState({ tasks: [truncated({ task_type: taskType, resource_id: resourceId }, true)] });
    const location = renderNote();

    expect(screen.getByRole("alert")).toHaveTextContent(`${lead}：${TRUNCATED}`);
    fireEvent.click(screen.getByRole("link", { name: "去登记最大输出长度" }));

    expect(location.history.at(-1)).toBe("/app/settings?section=providers&custom=7&model=my-llm");
  });

  it("asks to switch models when a built-in model is truncated", () => {
    useTasksStore.setState({ tasks: [truncated({ task_type: "text_episode_script", resource_id: "episode-1" }, false)] });
    renderNote();

    expect(screen.getByText(/请在设置中换一个文本模型后再试/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "去登记最大输出长度" })).not.toBeInTheDocument();
  });

  it("keeps the problem code, params and server text of a localized failure behind its details", () => {
    const summary = "custom-2/I2V_H3 不支持参考生视频；请在设置中为「参考生视频」单独指定支持该用途的模型，或更换默认视频模型";
    useTasksStore.setState({
      tasks: [
        failed({
          task_type: "text_reference_script_plan",
          resource_id: "episode-1",
          error_message: summary,
          error_code: "video_capability_missing_r2v",
          error_params: { provider: "custom-2", model: "I2V_H3" },
          error_detail: "❌ 服务端原文",
        }),
      ],
    });
    renderNote();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(`上一次 AI 规划脚本失败：${summary}`);
    expect(alert).not.toHaveTextContent("video_capability_missing_r2v");
    fireEvent.click(screen.getByRole("button", { name: "详情" }));

    expect(screen.getByText("video_capability_missing_r2v")).toBeInTheDocument();
    expect(screen.getByText("provider=custom-2, model=I2V_H3")).toBeInTheDocument();
    expect(screen.getByText("❌ 服务端原文")).toBeInTheDocument();
  });

  it("shows only the latest text task of this episode, until it is dismissed", () => {
    useTasksStore.setState({
      tasks: [
        failed({ task_id: "old", task_type: "text_episode_script", resource_id: "episode-1", error_message: "旧的失败" }),
        failed({
          task_id: "other-episode",
          task_type: "text_episode_script",
          resource_id: "episode-12",
          queued_at: "2026-10-01T12:00:00Z",
        }),
        failed({
          task_id: "new",
          task_type: "text_drama_script_plan",
          resource_id: "episode-1",
          queued_at: "2026-10-01T11:00:00Z",
          error_message: "源文读取失败",
        }),
      ],
    });
    renderNote();

    expect(screen.getByRole("alert")).toHaveTextContent("上一次 AI 规划脚本失败：源文读取失败");
    expect(screen.queryByRole("button", { name: "详情" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("stays away once the latest text task of this episode has not failed", () => {
    useTasksStore.setState({
      tasks: [
        failed({ task_type: "text_episode_script", resource_id: "episode-1" }),
        makeTask({
          project_name: "demo",
          task_type: "text_episode_script",
          resource_id: "episode-1",
          status: "running",
          queued_at: "2026-10-01T11:00:00Z",
        }),
      ],
    });
    renderNote();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    ["没有正式脚本时脚本文本任务一律是整份生成", { hasScript: false }, {}],
    ["有正式脚本时按违约失败的标记认出整份生成", { hasScript: true }, { error_code: "ad_script_rejected" }],
    ["有正式脚本时按整份重做的标记认出整份生成", { hasScript: true }, { payload: { regenerate: true } }],
  ])("labels an ad whole-script generation failure: %s", (_name, ad, overrides) => {
    useTasksStore.setState({
      tasks: [
        failed({
          task_type: "text_episode_script",
          resource_id: "episode-1",
          error_message: "AI 生成的脚本不合规",
          ...overrides,
        }),
      ],
    });
    renderNote(1, ad);

    expect(screen.getByRole("alert")).toHaveTextContent("上一次 AI 生成脚本失败：AI 生成的脚本不合规");
  });

  it("keeps prompt authoring failures of an ad episode with a script as prompt authoring", () => {
    useTasksStore.setState({
      tasks: [failed({ task_type: "text_episode_script", resource_id: "episode-1", error_message: "模型超时" })],
    });
    renderNote(1, { hasScript: true });

    expect(screen.getByRole("alert")).toHaveTextContent("上一次编写提示词失败：模型超时");
  });

  /** 把本集的工作流内容（含草稿列表）注入 workflow store，模拟服务端投影。 */
  function setWorkflowDrafts(drafts: WorkflowDraft[]) {
    useWorkflowStore.setState({
      plan: { status: { content: { drafts } } },
      planKey: "demo::1",
    } as unknown as Partial<ReturnType<typeof useWorkflowStore.getState>>);
  }

  it("hides the note once the violation draft it produced is resolved (promoted or discarded)", () => {
    // 违约失败：报告原文带「待修复草稿」，对应 reference_video_prompt_authoring 草稿种类。
    useTasksStore.setState({
      tasks: [
        failed({
          task_id: "pa-failed",
          task_type: "text_episode_script",
          resource_id: "episode-1",
          error_message: "❌ prompt_authoring 提示词编写产出有 1 处违约，已保存为待修复草稿（正式文件未被改动）：drafts/1_...json",
        }),
      ],
    });
    // 草稿已不在场（已晋升 / 丢弃）→ 问题已解决。
    setWorkflowDrafts([]);
    renderNote();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the note while the violation draft it produced is still outstanding", () => {
    useTasksStore.setState({
      tasks: [
        failed({
          task_id: "pa-failed",
          task_type: "text_episode_script",
          resource_id: "episode-1",
          error_message: "❌ prompt_authoring 提示词编写产出有 1 处违约，已保存为待修复草稿（正式文件未被改动）：drafts/1_...json",
        }),
      ],
    });
    setWorkflowDrafts([
      { kind: "reference_video_prompt_authoring", path: "drafts/episode_1/pa.json", needs_repair: true },
    ]);
    renderNote();

    expect(screen.getByRole("alert")).toHaveTextContent("上一次编写提示词失败");
  });

  it("re-surfaces a draft violation failure after dismiss when its draft is still outstanding", () => {
    // 违约失败：报告原文带「待修复草稿」，对应 reference_video_prompt_authoring 草稿种类。
    useTasksStore.setState({
      tasks: [
        failed({
          task_id: "pa-failed",
          task_type: "text_episode_script",
          resource_id: "episode-1",
          error_message: "❌ prompt_authoring 提示词编写产出有 1 处违约，已保存为待修复草稿（正式文件未被改动）：drafts/1_...json",
        }),
      ],
    });
    setWorkflowDrafts([
      { kind: "reference_video_prompt_authoring", path: "drafts/episode_1/pa.json", needs_repair: true },
    ]);
    const { unmount } = render(
      <Router hook={memoryLocation({ path: "/episodes/1" }).hook} searchHook={memoryLocation({ path: "/episodes/1" }).searchHook}>
        <TextTaskFailureNote projectName="demo" episode={1} isAd={false} hasScript />
      </Router>,
    );
    // 用户手动关闭（草稿类失败只静音当前挂载，不持久化）。
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // 重进集页：草稿仍在 needs_repair（真问题没解决）→ 重新弹出，而不是被关闭压住。
    unmount();
    render(
      <Router hook={memoryLocation({ path: "/episodes/1" }).hook} searchHook={memoryLocation({ path: "/episodes/1" }).searchHook}>
        <TextTaskFailureNote projectName="demo" episode={1} isAd={false} hasScript />
      </Router>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("keeps a pure failure (no draft produced) visible even when no draft is present", () => {
    // 模型超时：error_message 不含「待修复草稿」，是纯错误，不应因草稿不在场而隐藏。
    useTasksStore.setState({
      tasks: [failed({ task_type: "text_episode_script", resource_id: "episode-1", error_message: "模型超时" })],
    });
    setWorkflowDrafts([]);
    renderNote();

    expect(screen.getByRole("alert")).toHaveTextContent("上一次编写提示词失败：模型超时");
  });

  it("does not hide while the workflow content for this episode is not yet loaded", () => {
    useTasksStore.setState({
      tasks: [failed({ task_type: "text_episode_script", resource_id: "episode-1", error_message: "模型超时" })],
    });
    // planKey 不匹配本集 → 视为内容未取到，保守沿用现状（显示）。
    useWorkflowStore.setState({ plan: null, planKey: "other::9" });
    renderNote();

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("stays hidden after being dismissed, surviving a remount", () => {
    useTasksStore.setState({
      tasks: [failed({ task_id: "dismiss-me", task_type: "text_episode_script", resource_id: "episode-1", error_message: "模型超时" })],
    });
    localStorage.setItem(DISMISSED_KEY, JSON.stringify(["dismiss-me"]));
    const { unmount } = render(
      <Router hook={memoryLocation({ path: "/episodes/1" }).hook} searchHook={memoryLocation({ path: "/episodes/1" }).searchHook}>
        <TextTaskFailureNote projectName="demo" episode={1} isAd={false} hasScript />
      </Router>,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // 模拟重进集页（组件重新挂载）：从 localStorage 恢复已关闭状态。
    unmount();
    render(
      <Router hook={memoryLocation({ path: "/episodes/1" }).hook} searchHook={memoryLocation({ path: "/episodes/1" }).searchHook}>
        <TextTaskFailureNote projectName="demo" episode={1} isAd={false} hasScript />
      </Router>,
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
