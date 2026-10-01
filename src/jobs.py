class Action:
    def __init__(self, action_type, node_id, height=0, manual_coords=None):
        # action_type: "MOVE", "PICK", "DROP"
        self.action_type = action_type
        self.node_id = node_id
        self.height = height
        self.manual_coords = manual_coords # dict {"x": x, "y": y}
        # execution state for UI tracking: "pending", "executing", "failed"
        self.status = "pending"

    def to_dict(self):
        return {
            "action_type": self.action_type,
            "node_id": self.node_id,
            "height": self.height,
            "manual_coords": self.manual_coords,
            "status": self.status
        }

    def __repr__(self):
        if self.manual_coords:
            return f"[{self.status.upper()}] {self.action_type}(X:{self.manual_coords['x']}, Y:{self.manual_coords['y']}, H:{self.height})"
        return f"[{self.status.upper()}] {self.action_type}({self.node_id}, H:{self.height})"


class MacroJob:
    def __init__(self, name):
        self.name = name
        self.actions = []

    def add_action(self, action):
        self.actions.append(action)

    def get_actions(self):
        return self.actions

class PalletizingJob(MacroJob):
    def __init__(self, source_node, target_node, source_height, base_height, height_step, count):
        super().__init__("Palletizing")
        self.source_node = source_node
        self.target_node = target_node
        self.source_height = source_height
        self.base_height = base_height
        self.height_step = height_step
        self.count = count

        self._generate_sequence()

    def _generate_sequence(self):
        for i in range(self.count):
            # Move to source
            self.add_action(Action("MOVE", self.source_node))
            # Pick from source
            self.add_action(Action("PICK", self.source_node, self.source_height))
            # Move to target
            self.add_action(Action("MOVE", self.target_node))
            # Drop at target with increasing height
            drop_height = self.base_height + (i * self.height_step)
            self.add_action(Action("DROP", self.target_node, drop_height))

import threading

class QueueManager:
    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()

    def add_action(self, action):
        with self.lock:
            self.queue.append(action)

    def add_macro_job(self, macro_job):
        with self.lock:
            self.queue.extend(macro_job.get_actions())

    def get_next(self):
        with self.lock:
            if self.queue:
                return self.queue[0]
            return None

    def pop_next(self):
        with self.lock:
            if self.queue:
                return self.queue.pop(0)
            return None

    def clear(self):
        with self.lock:
            self.queue.clear()

    def get_queue(self):
        with self.lock:
            return list(self.queue)
