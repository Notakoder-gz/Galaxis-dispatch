import json
import math
import heapq

class Graph:
    def __init__(self):
        self.nodes = {}  # id -> {"x": int, "y": int}
        self.edges = {}  # id -> [connected_ids]

    def load_from_json(self, filepath):
        with open(filepath, 'r') as f:
            data = json.load(f)

        self.nodes = {}
        for node in data.get("nodes", []):
            self.nodes[node["id"]] = {"x": node["logic_x"], "y": node["logic_y"]}

        self.edges = {}
        for edge in data.get("edges", []):
            u, v = edge[0], edge[1]
            if u not in self.edges:
                self.edges[u] = []
            if v not in self.edges:
                self.edges[v] = []
            self.edges[u].append(v)
            self.edges[v].append(u) # Assuming undirected graph for AMRs generally

    def heuristic(self, node_a, node_b):
        # Manhattan distance
        return abs(self.nodes[node_a]["x"] - self.nodes[node_b]["x"]) + abs(self.nodes[node_a]["y"] - self.nodes[node_b]["y"])

    def find_path(self, start_id, end_id):
        if not self.nodes:
            return None
        if start_id not in self.nodes or end_id not in self.nodes:
            return None

        if start_id == end_id:
            return [start_id]

        open_set = []
        heapq.heappush(open_set, (0, start_id))
        came_from = {}

        g_score = {node: float('inf') for node in self.nodes}
        g_score[start_id] = 0

        f_score = {node: float('inf') for node in self.nodes}
        f_score[start_id] = self.heuristic(start_id, end_id)

        # Track elements currently in open_set to avoid O(N) lookup
        open_set_hash = {start_id}

        while open_set:
            _, current = heapq.heappop(open_set)
            open_set_hash.remove(current)

            if current == end_id:
                # Reconstruct path
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path

            for neighbor in self.edges.get(current, []):
                # distance between any two connected nodes is 1 or euclidian, let's use euclidian for actual cost
                dx = self.nodes[current]["x"] - self.nodes[neighbor]["x"]
                dy = self.nodes[current]["y"] - self.nodes[neighbor]["y"]
                weight = math.sqrt(dx*dx + dy*dy)

                tentative_g_score = g_score[current] + weight

                if tentative_g_score < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g_score
                    f_score[neighbor] = tentative_g_score + self.heuristic(neighbor, end_id)

                    if neighbor not in open_set_hash:
                        heapq.heappush(open_set, (f_score[neighbor], neighbor))
                        open_set_hash.add(neighbor)

        return None # No path found

    def get_node_id_by_coords(self, x, y):
        for node_id, coords in self.nodes.items():
            if coords["x"] == x and coords["y"] == y:
                return node_id
        return None
