/**
 * Graph layout algorithms for computing node positions.
 *
 * Supports multiple layout strategies:
 * - Dagre (hierarchical) — role-aware tiered layout
 * - Force-directed — exploratory graph browsing
 * - Radial — hub-and-spoke, site-centric views
 * - Path — left-to-right sequential for circuit/path queries
 * - Role-based hierarchical — network topology tiers (core/spine/leaf/access/server)
 *
 * All accept React Flow nodes/edges and return nodes with computed positions.
 */

import Dagre from "@dagrejs/dagre";
import type { Node, Edge } from "@xyflow/react";

export type LayoutDirection = "TB" | "BT" | "LR" | "RL";
export type LayoutMode = "hierarchical" | "force" | "radial" | "path" | "role-tiered";

const NODE_WIDTH = 140;
const NODE_HEIGHT = 60;

// --------------------------------------------------------------------------
// Role-based tier mapping for network topology
// --------------------------------------------------------------------------

const ROLE_TIERS: Record<string, number> = {
  // Device roles
  router: 0,
  firewall: 1,
  switch: 2,
  load_balancer: 1,
  wireless_controller: 2,
  wireless_ap: 3,
  server: 4,
  virtual_machine: 5,
  container_host: 5,
  other: 3,
};

const HOSTNAME_TIER_HINTS: [RegExp, number][] = [
  [/COR|CORE/i, 0],
  [/T2B|BORDER|WAN/i, 0],
  [/FW|FIRE/i, 1],
  [/SPN|SPINE/i, 1],
  [/LEAF/i, 2],
  [/ACC|ACCESS|DIST/i, 2],
  [/SRV|SERVER|HOST/i, 3],
  [/BR-|BRANCH/i, 2],
];

const NODE_TYPE_TIERS: Record<string, number> = {
  Provider: -1,
  Circuit: 0,
  CircuitTermination: 0,
  Location: -1,
  Device: 1,       // Default, overridden by role/hostname
  Interface: 5,    // Attached to devices
  MACAddress: 6,
  IPAddress: 6,
  Prefix: 5,
  Tenant: -1,
  Architecture: -2,
};

function inferTier(node: Node): number {
  const data = node.data as Record<string, any>;
  const nodeType = data?.nodeType || "";
  const props = data?.properties || {};
  const hostname = props.hostname || props.name || data?.label || "";
  const role = props.role || "";

  // Check hostname hints first (most specific)
  for (const [pattern, tier] of HOSTNAME_TIER_HINTS) {
    if (pattern.test(hostname)) return tier;
  }

  // Check device role
  if (role && ROLE_TIERS[role] !== undefined) {
    return ROLE_TIERS[role];
  }

  // Check node type
  if (NODE_TYPE_TIERS[nodeType] !== undefined) {
    return NODE_TYPE_TIERS[nodeType];
  }

  return 3; // Default middle tier
}

// --------------------------------------------------------------------------
// Dagre Hierarchical Layout
// --------------------------------------------------------------------------

export function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  direction: LayoutDirection = "TB",
): Node[] {
  if (nodes.length === 0) return [];

  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    nodesep: 60,
    ranksep: 100,
    edgesep: 25,
    marginx: 30,
    marginy: 30,
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
    return {
      ...node,
      position: {
        x: dagNode.x - NODE_WIDTH / 2,
        y: dagNode.y - NODE_HEIGHT / 2,
      },
    };
  });
}

// --------------------------------------------------------------------------
// Role-Tiered Layout (Network Topology Aware)
// --------------------------------------------------------------------------

export function applyRoleTieredLayout(
  nodes: Node[],
  edges: Edge[],
  direction: LayoutDirection = "TB",
): Node[] {
  if (nodes.length === 0) return [];

  // Assign tiers
  const tierMap = new Map<string, number>();
  for (const node of nodes) {
    tierMap.set(node.id, inferTier(node));
  }

  // Group by tier
  const tiers = new Map<number, Node[]>();
  for (const node of nodes) {
    const tier = tierMap.get(node.id) ?? 3;
    if (!tiers.has(tier)) tiers.set(tier, []);
    tiers.get(tier)!.push(node);
  }

  // Sort tier keys
  const sortedTiers = [...tiers.keys()].sort((a, b) => a - b);

  const isVertical = direction === "TB" || direction === "BT";
  const reversed = direction === "BT" || direction === "RL";

  const positions = new Map<string, { x: number; y: number }>();
  const tierSpacing = isVertical ? 150 : 200;
  const nodeSpacing = isVertical ? 180 : 120;

  for (let tierIdx = 0; tierIdx < sortedTiers.length; tierIdx++) {
    const tier = sortedTiers[reversed ? sortedTiers.length - 1 - tierIdx : tierIdx];
    const tierNodes = tiers.get(tier) || [];
    const tierWidth = tierNodes.length * nodeSpacing;
    const startOffset = -tierWidth / 2 + nodeSpacing / 2;

    for (let i = 0; i < tierNodes.length; i++) {
      const primaryPos = tierIdx * tierSpacing + 50;
      const secondaryPos = startOffset + i * nodeSpacing;

      if (isVertical) {
        positions.set(tierNodes[i].id, { x: secondaryPos + 400, y: primaryPos });
      } else {
        positions.set(tierNodes[i].id, { x: primaryPos, y: secondaryPos + 300 });
      }
    }
  }

  return nodes.map((node) => {
    const pos = positions.get(node.id) || { x: 0, y: 0 };
    return { ...node, position: pos };
  });
}

// --------------------------------------------------------------------------
// Radial Layout (Hub and Spoke)
// --------------------------------------------------------------------------

export function applyRadialLayout(
  nodes: Node[],
  edges: Edge[],
): Node[] {
  if (nodes.length === 0) return [];
  if (nodes.length === 1) return [{ ...nodes[0], position: { x: 400, y: 300 } }];

  // Find the most connected node as the center
  const connectionCount = new Map<string, number>();
  for (const node of nodes) connectionCount.set(node.id, 0);
  for (const edge of edges) {
    connectionCount.set(edge.source, (connectionCount.get(edge.source) || 0) + 1);
    connectionCount.set(edge.target, (connectionCount.get(edge.target) || 0) + 1);
  }

  const sorted = [...connectionCount.entries()].sort((a, b) => b[1] - a[1]);
  const centerId = sorted[0]?.[0];

  // Build adjacency for BFS layering
  const adj = new Map<string, Set<string>>();
  for (const node of nodes) adj.set(node.id, new Set());
  for (const edge of edges) {
    adj.get(edge.source)?.add(edge.target);
    adj.get(edge.target)?.add(edge.source);
  }

  // BFS from center to get rings
  const rings = new Map<string, number>();
  const queue = [centerId];
  rings.set(centerId, 0);
  while (queue.length > 0) {
    const current = queue.shift()!;
    const ring = rings.get(current)!;
    for (const neighbor of adj.get(current) || []) {
      if (!rings.has(neighbor)) {
        rings.set(neighbor, ring + 1);
        queue.push(neighbor);
      }
    }
  }

  // Position nodes in concentric rings
  const ringGroups = new Map<number, string[]>();
  for (const [id, ring] of rings) {
    if (!ringGroups.has(ring)) ringGroups.set(ring, []);
    ringGroups.get(ring)!.push(id);
  }
  // Nodes not reached by BFS
  const unreached = nodes.filter((n) => !rings.has(n.id));
  if (unreached.length > 0) {
    const maxRing = Math.max(...ringGroups.keys(), 0) + 1;
    ringGroups.set(maxRing, unreached.map((n) => n.id));
  }

  const centerX = 500;
  const centerY = 400;
  const ringSpacing = 150;

  const positions = new Map<string, { x: number; y: number }>();

  for (const [ring, ids] of ringGroups) {
    if (ring === 0) {
      positions.set(ids[0], { x: centerX, y: centerY });
      continue;
    }
    const radius = ring * ringSpacing;
    for (let i = 0; i < ids.length; i++) {
      const angle = (2 * Math.PI * i) / ids.length - Math.PI / 2;
      positions.set(ids[i], {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      });
    }
  }

  return nodes.map((node) => ({
    ...node,
    position: positions.get(node.id) || { x: centerX, y: centerY },
  }));
}

// --------------------------------------------------------------------------
// Path Layout (Left-to-Right Sequential)
// --------------------------------------------------------------------------

export function applyPathLayout(
  nodes: Node[],
  edges: Edge[],
): Node[] {
  if (nodes.length === 0) return [];

  // Build adjacency
  const adj = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  for (const node of nodes) {
    adj.set(node.id, []);
    inDegree.set(node.id, 0);
  }
  for (const edge of edges) {
    if (adj.has(edge.source) && adj.has(edge.target)) {
      adj.get(edge.source)!.push(edge.target);
      inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1);
    }
  }

  // Find path start (lowest in-degree)
  let startId = nodes[0].id;
  let minIn = Infinity;
  for (const [id, deg] of inDegree) {
    if (deg < minIn) { minIn = deg; startId = id; }
  }

  // BFS to get order
  const visited = new Set<string>();
  const order: string[] = [];
  const queue = [startId];
  visited.add(startId);
  while (queue.length > 0) {
    const current = queue.shift()!;
    order.push(current);
    for (const neighbor of adj.get(current) || []) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        queue.push(neighbor);
      }
    }
  }
  // Add any unvisited nodes
  for (const node of nodes) {
    if (!visited.has(node.id)) order.push(node.id);
  }

  const spacing = 200;
  const positions = new Map<string, { x: number; y: number }>();
  for (let i = 0; i < order.length; i++) {
    // Slight vertical offset for alternating nodes to avoid overlap
    const yOffset = (i % 2) * 30;
    positions.set(order[i], { x: 50 + i * spacing, y: 200 + yOffset });
  }

  return nodes.map((node) => ({
    ...node,
    position: positions.get(node.id) || { x: 0, y: 0 },
  }));
}

// --------------------------------------------------------------------------
// Force-Directed Layout
// --------------------------------------------------------------------------

export function applyForceLayout(nodes: Node[], edges: Edge[]): Node[] {
  if (nodes.length === 0) return [];
  if (nodes.length === 1) {
    return [{ ...nodes[0], position: { x: 400, y: 300 } }];
  }

  const ITERATIONS = 300;
  const AREA = Math.max(800, nodes.length * 200);
  const k = Math.sqrt(AREA / nodes.length);
  const COOLING_FACTOR = 0.95;

  const positions = new Map<string, { x: number; y: number }>();
  const radius = Math.max(250, nodes.length * 18);
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    positions.set(node.id, {
      x: 400 + radius * Math.cos(angle),
      y: 300 + radius * Math.sin(angle),
    });
  });

  let temperature = AREA / 10;

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const displacements = new Map<string, { dx: number; dy: number }>();
    for (const node of nodes) displacements.set(node.id, { dx: 0, dy: 0 });

    // Repulsive forces
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
        displacements.get(nodes[i].id)!.dx += dx;
        displacements.get(nodes[i].id)!.dy += dy;
        displacements.get(nodes[j].id)!.dx -= dx;
        displacements.get(nodes[j].id)!.dy -= dy;
      }
    }

    // Attractive forces
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
      displacements.get(edge.source)!.dx -= dx;
      displacements.get(edge.source)!.dy -= dy;
      displacements.get(edge.target)!.dx += dx;
      displacements.get(edge.target)!.dy += dy;
    }

    // Apply
    for (const node of nodes) {
      const disp = displacements.get(node.id)!;
      const pos = positions.get(node.id)!;
      const dist = Math.max(Math.sqrt(disp.dx * disp.dx + disp.dy * disp.dy), 0.01);
      const capped = Math.min(dist, temperature);
      pos.x += (disp.dx / dist) * capped;
      pos.y += (disp.dy / dist) * capped;
    }

    temperature *= COOLING_FACTOR;
  }

  // Normalize
  let minX = Infinity, minY = Infinity;
  for (const pos of positions.values()) {
    minX = Math.min(minX, pos.x);
    minY = Math.min(minY, pos.y);
  }

  return nodes.map((node) => {
    const pos = positions.get(node.id)!;
    return { ...node, position: { x: pos.x - minX + 30, y: pos.y - minY + 30 } };
  });
}

// --------------------------------------------------------------------------
// Layout dispatcher
// --------------------------------------------------------------------------

export function applyLayout(
  mode: LayoutMode,
  nodes: Node[],
  edges: Edge[],
  direction: LayoutDirection = "TB",
): Node[] {
  switch (mode) {
    case "hierarchical": return applyDagreLayout(nodes, edges, direction);
    case "force": return applyForceLayout(nodes, edges);
    case "radial": return applyRadialLayout(nodes, edges);
    case "path": return applyPathLayout(nodes, edges);
    case "role-tiered": return applyRoleTieredLayout(nodes, edges, direction);
    default: return applyDagreLayout(nodes, edges, direction);
  }
}
