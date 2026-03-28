/**
 * Graph layout algorithms for computing node positions.
 *
 * Supports dagre (hierarchical) and a simple force-directed layout.
 * Both accept React Flow nodes/edges and return nodes with computed positions.
 */

import Dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";

export type LayoutDirection = "TB" | "BT" | "LR" | "RL";

const NODE_WIDTH = 120;
const NODE_HEIGHT = 60;

/**
 * Apply dagre hierarchical layout to a set of nodes and edges.
 * Returns a new array of nodes with updated x,y positions.
 */
export function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  direction: LayoutDirection = "TB",
): Node[] {
  if (nodes.length === 0) return [];

  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    nodesep: 50,
    ranksep: 80,
    edgesep: 20,
    marginx: 20,
    marginy: 20,
  });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }

  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  Dagre.layout(g);

  return nodes.map((node) => {
    const dagNode = g.node(node.id);
    // dagre gives center coordinates; React Flow positions from top-left
    return {
      ...node,
      position: {
        x: dagNode.x - NODE_WIDTH / 2,
        y: dagNode.y - NODE_HEIGHT / 2,
      },
    };
  });
}

/**
 * Simple force-directed layout using a spring-charge simulation.
 *
 * This is a lightweight implementation that does not require d3-force.
 * It uses Fruchterman-Reingold-style repulsion/attraction forces
 * iterated a fixed number of times for deterministic results.
 */
export function applyForceLayout(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return [];
  if (nodes.length === 1) {
    return [{ ...nodes[0], position: { x: 0, y: 0 } }];
  }

  const ITERATIONS = 300;
  const AREA = Math.max(600, nodes.length * 150);
  const k = Math.sqrt(AREA / nodes.length); // ideal distance
  const COOLING_FACTOR = 0.95;

  // Initialize positions in a circle to avoid overlaps at start
  const positions = new Map<string, { x: number; y: number }>();
  const radius = Math.max(200, nodes.length * 15);
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    positions.set(node.id, {
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
    });
  });

  let temperature = AREA / 10;

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const displacements = new Map<string, { dx: number; dy: number }>();
    for (const node of nodes) {
      displacements.set(node.id, { dx: 0, dy: 0 });
    }

    // Repulsive forces between all pairs
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const posI = positions.get(nodes[i].id)!;
        const posJ = positions.get(nodes[j].id)!;
        let dx = posI.x - posJ.x;
        let dy = posI.y - posJ.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
        const force = (k * k) / dist;
        dx = (dx / dist) * force;
        dy = (dy / dist) * force;

        const dispI = displacements.get(nodes[i].id)!;
        const dispJ = displacements.get(nodes[j].id)!;
        dispI.dx += dx;
        dispI.dy += dy;
        dispJ.dx -= dx;
        dispJ.dy -= dy;
      }
    }

    // Attractive forces along edges
    for (const edge of edges) {
      const posS = positions.get(edge.source);
      const posT = positions.get(edge.target);
      if (!posS || !posT) continue;

      let dx = posS.x - posT.x;
      let dy = posS.y - posT.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 0.01);
      const force = (dist * dist) / k;
      dx = (dx / dist) * force;
      dy = (dy / dist) * force;

      const dispS = displacements.get(edge.source)!;
      const dispT = displacements.get(edge.target)!;
      dispS.dx -= dx;
      dispS.dy -= dy;
      dispT.dx += dx;
      dispT.dy += dy;
    }

    // Apply displacements with temperature limiting
    for (const node of nodes) {
      const disp = displacements.get(node.id)!;
      const pos = positions.get(node.id)!;
      const dist = Math.max(Math.sqrt(disp.dx * disp.dx + disp.dy * disp.dy), 0.01);
      const cappedDist = Math.min(dist, temperature);
      pos.x += (disp.dx / dist) * cappedDist;
      pos.y += (disp.dy / dist) * cappedDist;
    }

    temperature *= COOLING_FACTOR;
  }

  // Normalize so minimum position is at origin
  let minX = Infinity;
  let minY = Infinity;
  for (const pos of positions.values()) {
    minX = Math.min(minX, pos.x);
    minY = Math.min(minY, pos.y);
  }

  return nodes.map((node) => {
    const pos = positions.get(node.id)!;
    return {
      ...node,
      position: {
        x: pos.x - minX + 20,
        y: pos.y - minY + 20,
      },
    };
  });
}
