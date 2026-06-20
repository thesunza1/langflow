import type {
  Connection,
  Node,
  OnEdgesChange,
  OnNodesChange,
  ReactFlowInstance,
  Viewport,
} from "@xyflow/react";
import type { AllNodeType, EdgeType, FlowType } from "@/types/flow";
import type { BuildStatus, EventDeliveryType } from "../../../constants/enums";
import type { LogsLogType, VertexBuildTypeAPI } from "../../api";
import type { ChatInputType, ChatOutputType } from "../../chat";
import type { FlowState } from "../../tabs";


// ─── Build Instance (multi-build support) ───────────────────────────────
export type BuildInstanceStatus =
  | "pending"      // Enqueued, waiting for resources
  | "running"      // Actively building
  | "completed"    // Successfully built all vertices
  | "error"        // Build failed
  | "cancelled";   // Cancelled by user

export interface BuildInstance {
  buildId: string;
  startNodeId?: string;
  stopNodeId?: string;
  input_value?: string;
  files?: string[];
  silent?: boolean;
  session?: string;
  stream?: boolean;
  status: BuildInstanceStatus;
  /** Per-instance vertex build state (replaces global verticesBuild) */
  verticesBuild: {
    verticesIds: string[];
    verticesLayers: VertexLayerElementType[][];
    runId?: string;
    verticesToRun: string[];
  } | null;
  /** Per-instance flow build status (replaces global flowBuildStatus) */
  flowBuildStatus: {
    [key: string]: {
      status: BuildStatus;
      timestamp?: string;
    };
  };
  /** Per-instance flow pool (augments global flowPool) */
  flowPool: Record<string, VertexBuildTypeAPI[]>;
  /** AbortController for this specific build */
  abortController: AbortController;
  /** When the build instance was created */
  createdAt: number;
}

// ─── End Build Instance ─────────────────────────────────────────────────

export type FlowPoolObjectType = {
  timestamp: string;
  valid: boolean;
  messages: Array<ChatOutputType | ChatInputType> | [];
  data: {
    artifacts: any | ChatOutputType | ChatInputType;
    results: any | ChatOutputType | ChatInputType;
  };
  duration?: string;
  progress?: number;
  id: string;
  buildId: string;
};

export type FlowPoolObjectTypeNew = {
  //build
  //1 - error->logs
  //2 - success-> result
  timestamp: string;
  valid: boolean;
  data: {
    outputs?: any | ChatOutputType | ChatInputType;
    results: any | ChatOutputType | ChatInputType;
  };
  duration?: string;
  progress?: number;
  //retrieve component type from id
  id: string;
  buildId: string;
};

export type VertexLayerElementType = {
  id: string;
  reference?: string;
};

export type FlowPoolType = {
  [key: string]: Array<VertexBuildTypeAPI>;
};

export type ComponentsToUpdateType = {
  id: string;
  icon?: string;
  display_name: string;
  outdated: boolean;
  blocked: boolean;
  breakingChange: boolean;
  userEdited: boolean;
};

export type FlowStoreType = {
  dismissedNodes: string[];
  addDismissedNodes: (dismissedNodes: string[]) => void;
  removeDismissedNodes: (dismissedNodes: string[]) => void;
  dismissedNodesLegacy: string[];
  addDismissedNodesLegacy: (dismissedNodes: string[]) => void;
  //key x, y
  positionDictionary: { [key: number]: number };
  isPositionAvailable: (position: { x: number; y: number }) => boolean;
  setPositionDictionary: (positionDictionary: {
    [key: number]: number;
  }) => void;
  fitViewNode: (nodeId: string) => void;
  autoSaveFlow: ((flow?: FlowType) => void) | undefined;
  componentsToUpdate: ComponentsToUpdateType[];
  setComponentsToUpdate: (
    update:
      | ComponentsToUpdateType[]
      | ((oldState: ComponentsToUpdateType[]) => ComponentsToUpdateType[]),
  ) => void;
  updateComponentsToUpdate: (nodes: AllNodeType[]) => void;
  onFlowPage: boolean;
  setOnFlowPage: (onFlowPage: boolean) => void;
  flowPool: FlowPoolType;
  setHasIO: (hasIO: boolean) => void;
  setInputs: (
    inputs: Array<{ type: string; id: string; displayName: string }>,
  ) => void;
  setOutputs: (
    outputs: Array<{ type: string; id: string; displayName: string }>,
  ) => void;
  inputs: Array<{
    type: string;
    id: string;
    displayName: string;
  }>;
  outputs: Array<{
    type: string;
    id: string;
    displayName: string;
  }>;
  hasIO: boolean;
  setFlowPool: (flowPool: FlowPoolType) => void;
  addDataToFlowPool: (data: VertexBuildTypeAPI, nodeId: string) => void;
  appendLogToFlowPool: (
    nodeId: string,
    outputName: string,
    log: LogsLogType,
  ) => void;
  CleanFlowPool: () => void;
  isBuilding: boolean;
  buildStartTime: number | null;
  buildDuration: number | null;
  buildingFlowId: string | null;
  buildingSessionId: string | null;
  isPending: boolean;
  setIsBuilding: (isBuilding: boolean) => void;
  setBuildStartTime: (time: number) => void;
  setBuildDuration: (duration: number) => void;
  setBuildingSession: (flowId: string | null, sessionId: string | null) => void;
  processNextBuildQueue: () => Promise<void>;
  setPending: (isPending: boolean) => void;
  resetFlow: (flow: FlowType | undefined) => void;
  resetFlowState: () => void;
  reactFlowInstance: ReactFlowInstance<AllNodeType, EdgeType> | null;
  setReactFlowInstance: (
    newState: ReactFlowInstance<AllNodeType, EdgeType>,
  ) => void;
  flowState: FlowState | undefined;
  setFlowState: (
    state:
      | FlowState
      | undefined
      | ((oldState: FlowState | undefined) => FlowState),
  ) => void;
  nodes: AllNodeType[];
  edges: EdgeType[];
  onNodesChange: OnNodesChange<AllNodeType>;
  onEdgesChange: OnEdgesChange<EdgeType>;
  setNodes: (
    update: AllNodeType[] | ((oldState: AllNodeType[]) => AllNodeType[]),
  ) => void;
  setEdges: (
    update: EdgeType[] | ((oldState: EdgeType[]) => EdgeType[]),
  ) => void;
  setNode: (
    id: string,
    update: AllNodeType | ((oldState: AllNodeType) => AllNodeType),
    isUserChange?: boolean,
    callback?: () => void,
  ) => void;
  getNode: (id: string) => AllNodeType | undefined;
  deleteNode: (nodeId: string | Array<string>) => void;
  deleteEdge: (edgeId: string | Array<string>) => void;
  paste: (
    selection: { nodes: any; edges: any },
    position: { x: number; y: number; paneX?: number; paneY?: number },
  ) => void;
  lastCopiedSelection: { nodes: any; edges: any } | null;
  setLastCopiedSelection: (
    newSelection: { nodes: any; edges: any } | null,
    isCrop?: boolean,
  ) => void;
  cleanFlow: () => void;
  setFilterEdge: (newState) => void;
  getFilterEdge: any[];
  setFilterComponent: (newState) => void;
  getFilterComponent: string;
  rightClickedNodeId: string | null;
  setRightClickedNodeId: (nodeId: string | null) => void;
  onConnect: (connection: Connection) => void;
  unselectAll: () => void;
  playgroundPage: boolean;
  setPlaygroundPage: (playgroundPage: boolean) => void;
  buildInfo: { error?: string[]; success?: boolean } | null;
  setBuildInfo: (
    buildInfo: { error?: string[]; success?: boolean } | null,
  ) => void;

  // ─── Multi-build instance API ──────────────────────────────────────────
  /** Map of all build instances (active, pending, completed). */
  buildInstances: Record<string, BuildInstance>;

  /** Create a new build instance and add it to the map. */
  createBuildInstance: (params: {
    startNodeId?: string;
    stopNodeId?: string;
    input_value?: string;
    files?: string[];
    silent?: boolean;
    session?: string;
    stream?: boolean;
  }) => BuildInstance;

  /** Update an existing build instance. */
  updateBuildInstance: (
    buildId: string,
    patch: Partial<BuildInstance>,
  ) => void;

  /** Remove a build instance from the map. */
  deleteBuildInstance: (buildId: string) => void;

  /** Get a specific build instance by id. */
  getBuildInstance: (buildId: string) => BuildInstance | undefined;

  /** True if any build instance is currently running. */
  isAnyBuilding: () => boolean;

  /** Return all build instances that include the given node in their vertices. */
  getBuildInstancesForNode: (nodeId: string) => BuildInstance[];

  /**
   * Compute the effective build status for a node across ALL build instances.
   * BUILDING wins over everything, then ERROR, then TO_BUILD, then BUILT.
   */
  getBuildStatusForNode: (nodeId: string) => BuildStatus | undefined;

  /** Abort (cancel) a specific build instance. */
  abortBuildInstance: (buildId: string) => void;

  /** Stop all build instances that include the given node. */
  stopBuildingForNode: (nodeId: string) => void;

  /** Process the build queue: pick the next non-conflicting pending build and run it. */
  processBuildQueue: () => Promise<void>;
  // ─── End multi-build instance API ──────────────────────────────────────

  buildQueue: Array<{
    startNodeId?: string;
    stopNodeId?: string;
    input_value?: string;
    files?: string[];
    silent?: boolean;
    session?: string;
    stream?: boolean;
    eventDelivery?: EventDeliveryType;
  }>;
  pastBuildFlowParams: {
    startNodeId?: string;
    stopNodeId?: string;
    input_value?: string;
    files?: string[];
    silent?: boolean;
    session?: string;
    stream?: boolean;
    eventDelivery?: EventDeliveryType;
  } | null;
  buildFlow: ({
    startNodeId,
    stopNodeId,
    input_value,
    files,
    silent,
    session,
    stream,
    eventDelivery,
  }: {
    startNodeId?: string;
    stopNodeId?: string;
    input_value?: string;
    files?: string[];
    silent?: boolean;
    session?: string;
    stream?: boolean;
    eventDelivery?: EventDeliveryType;
  }) => Promise<void>;
  getFlow: () => { nodes: Node[]; edges: EdgeType[]; viewport: Viewport };
  updateVerticesBuild: (
    vertices: {
      verticesIds: string[];
      verticesLayers: VertexLayerElementType[][];
      runId?: string;
      verticesToRun: string[];
    } | null,
  ) => void;
  addToVerticesBuild: (vertices: string[]) => void;
  removeFromVerticesBuild: (vertices: string[]) => void;
  verticesBuild: {
    verticesIds: string[];
    verticesLayers: VertexLayerElementType[][];
    runId?: string;
    verticesToRun: string[];
  } | null;
  updateBuildStatus: (nodeIdList: string[], status: BuildStatus) => void;
  revertBuiltStatusFromBuilding: () => void;
  latestRunningText: Record<string, string[]>;
  setLatestRunningText: (nodeId: string, text: string) => void;
  flowBuildStatus: {
    [key: string]: {
      status: BuildStatus;
      timestamp?: string;
    };
  };
  updateFlowPool: (
    nodeId: string,
    data: VertexBuildTypeAPI | ChatOutputType | ChatInputType,
    buildId?: string,
  ) => void;
  getNodePosition: (nodeId: string) => { x: number; y: number };
  updateFreezeStatus: (nodeIds: string[], freeze: boolean) => void;
  currentFlow: FlowType | undefined;
  setCurrentFlow: (flow: FlowType | undefined) => void;
  updateCurrentFlow: ({
    nodes,
    edges,
    viewport,
  }: {
    nodes?: AllNodeType[];
    edges?: EdgeType[];
    viewport?: Viewport;
  }) => void;
  handleDragging:
    | {
        source: string | undefined;
        sourceHandle: string | undefined;
        target: string | undefined;
        targetHandle: string | undefined;
        type: string;
        color: string;
      }
    | undefined;
  setHandleDragging: (
    data:
      | {
          source: string | undefined;
          sourceHandle: string | undefined;
          target: string | undefined;
          targetHandle: string | undefined;
          type: string;
          color: string;
        }
      | undefined,
  ) => void;

  filterType:
    | {
        source: string | undefined;
        sourceHandle: string | undefined;
        target: string | undefined;
        targetHandle: string | undefined;
        type: string;
        color: string;
      }
    | undefined;
  setFilterType: (
    data:
      | {
          source: string | undefined;
          sourceHandle: string | undefined;
          target: string | undefined;
          targetHandle: string | undefined;
          type: string;
          color: string;
        }
      | undefined,
  ) => void;
  updateEdgesRunningByNodes: (ids: string[], running: boolean) => void;
  stopBuilding: () => void;
  buildController: AbortController;
  setBuildController: (controller: AbortController) => void;
  buildControllerSet: Set<AbortController>;
  addBuildController: (controller: AbortController) => void;
  removeBuildController: (controller: AbortController) => void;
  currentBuildingNodeId: string[] | undefined;
  setCurrentBuildingNodeId: (nodeIds: string[] | undefined) => void;
  clearEdgesRunningByNodes: () => Promise<void>;
  clearAndSetEdgesRunning: (nextIds?: string[]) => void;
  /** Recompute edge animation state from all running build instances. */
  computeEdgeRunningFromBuilds: () => void;
  updateToolMode: (nodeId: string, toolMode: boolean) => void;
  helperLineEnabled: boolean;
  setHelperLineEnabled: (helperLineEnabled: boolean) => void;
  inspectionPanelVisible: boolean;
  setInspectionPanelVisible: (visible: boolean) => void;
  newChatOnPlayground: boolean;
  setNewChatOnPlayground: (newChat: boolean) => void;
  stopNodeId: string | undefined;
  setStopNodeId: (nodeId: string | undefined) => void;
};
