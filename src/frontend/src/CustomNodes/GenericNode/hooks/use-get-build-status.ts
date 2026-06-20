import { BuildStatus } from "@/constants/enums";
import useFlowStore from "@/stores/flowStore";
import type { NodeDataType } from "@/types/flow";

const STATUS_PRIORITY: Record<string, number> = {
  BUILDING: 5,
  ERROR: 4,
  TO_BUILD: 3,
  BUILT: 2,
  INACTIVE: 1,
};

/** Merge status from global flowBuildStatus AND all running build instances.
 *  The highest-priority status wins. This ensures correct display when
 *  multiple builds run in parallel (multi-build). */
function mergeBuildStatus(
  globalStatus: BuildStatus | undefined,
  buildInstances: Record<string, any>,
  nodeId: string,
): BuildStatus | undefined {
  let best = globalStatus;
  let bestPrio = best ? (STATUS_PRIORITY[best] ?? 0) : 0;

  for (const inst of Object.values(buildInstances)) {
    if (inst.status !== "running" && inst.status !== "pending") continue;

    // Check per-instance flowBuildStatus
    const instEntry = inst.flowBuildStatus?.[nodeId];
    if (instEntry?.status) {
      const p = STATUS_PRIORITY[instEntry.status] ?? 0;
      if (p > bestPrio) {
        bestPrio = p;
        best = instEntry.status;
      }
    }

    // If this build targets this node (stopNodeId) and no status yet → BUILDING
    if (inst.stopNodeId === nodeId && !best) {
      best = BuildStatus.BUILDING;
      bestPrio = STATUS_PRIORITY.BUILDING;
    }
  }

  return best;
}

export const useBuildStatus = (data: NodeDataType, nodeId: string) => {
  return useFlowStore((state) => {
    // Global status from the shared flowBuildStatus map
    const globalStatus = state.flowBuildStatus[nodeId]?.status;

    // Merge with per-build-instance statuses for multi-build accuracy
    const merged = mergeBuildStatus(globalStatus, state.buildInstances, nodeId);

    // If this node is a group with sub-nodes, handle that too
    if (!data.node?.flow?.data?.nodes) {
      return merged;
    }

    // For group nodes: merge status across all sub-nodes
    const nodes = data.node.flow.data.nodes;
    const buildStatuses = nodes
      .map((node) => {
        const gs = state.flowBuildStatus[node.id]?.status;
        return mergeBuildStatus(gs, state.buildInstances, node.id);
      })
      .filter(Boolean);

    if (buildStatuses.length === 0) {
      return merged;
    }

    if (buildStatuses.every((status) => status === BuildStatus.BUILT)) {
      return BuildStatus.BUILT;
    }
    if (buildStatuses.some((status) => status === BuildStatus.BUILDING)) {
      return BuildStatus.BUILDING;
    }
    if (buildStatuses.some((status) => status === BuildStatus.ERROR)) {
      return BuildStatus.ERROR;
    }

    return BuildStatus.TO_BUILD;
  });
};
