import { describe, it, expect } from "@jest/globals";
import { findNearestBuiltUpstream } from "../buildUtils";

describe("findNearestBuiltUpstream", () => {
  const edges = [
    { source: "A", target: "B" },
    { source: "B", target: "C" },
    { source: "C", target: "D" },
  ] as any;

  const allBuilt: Record<string, { status: string }> = {
    A: { status: "BUILT" },
    B: { status: "BUILT" },
    C: { status: "BUILT" },
  };

  const noneBuilt: Record<string, { status: string }> = {
    A: { status: "TO_BUILD" },
    B: { status: "TO_BUILD" },
    C: { status: "BUILDING" },
  };

  const ABuilt: Record<string, { status: string }> = {
    A: { status: "BUILT" },
    B: { status: "TO_BUILD" },
    C: { status: "BUILDING" },
  };

  const BOnlyBuilt: Record<string, { status: string }> = {
    A: { status: "TO_BUILD" },
    B: { status: "BUILT" },
    C: { status: "ERROR" },
  };

  it("returns null when node has no predecessors", () => {
    expect(findNearestBuiltUpstream("A", edges, allBuilt)).toBeNull();
  });

  it("returns the nearest built predecessor (direct)", () => {
    // D's direct predecessor is C, which is built
    expect(findNearestBuiltUpstream("D", edges, allBuilt)).toBe("C");
  });

  it("returns the nearest built predecessor (BFS, not direct)", () => {
    // C's direct predecessor is B (not built), but A is built further up
    expect(findNearestBuiltUpstream("C", edges, ABuilt)).toBe("A");
  });

  it("returns the first found built predecessor in BFS order", () => {
    // D's direct predecessor C is not built, B is built
    expect(findNearestBuiltUpstream("D", edges, BOnlyBuilt)).toBe("B");
  });

  it("returns null when no upstream nodes are built", () => {
    expect(findNearestBuiltUpstream("D", edges, noneBuilt)).toBeNull();
  });

  it("returns null when called on start node with no incoming edges", () => {
    expect(findNearestBuiltUpstream("A", edges, allBuilt)).toBeNull();
  });

  it("handles empty edges", () => {
    expect(findNearestBuiltUpstream("A", [], allBuilt)).toBeNull();
  });

  it("handles empty flowBuildStatus", () => {
    expect(findNearestBuiltUpstream("B", edges, {})).toBeNull();
  });
});
