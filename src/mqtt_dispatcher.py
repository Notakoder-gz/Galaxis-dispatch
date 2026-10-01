import json
import time
import threading
import paho.mqtt.client as mqtt

class Dispatcher:
    def __init__(self, graph, queue_manager):
        self.graph = graph
        self.queue_manager = queue_manager

        self.client = mqtt.Client(client_id="wcs_dispatcher")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self.host = "127.0.0.1"
        self.port = 1883

        self.pub_topic = "/wcs_server/30"
        self.sub_topic = "/agv_robot/status"

        self.current_pos = {"x": 0, "y": 0}
        self.expected_dest = None

        self.is_running = False
        self.is_paused = False

        self.log_callback = None
        self.queue_update_callback = None

        self.last_sent_action = None
        self.waiting_for_completion = False

        # Thread safety lock
        self.lock = threading.Lock()

    def set_log_callback(self, cb):
        self.log_callback = cb

    def set_queue_update_callback(self, cb):
        self.queue_update_callback = cb

    def notify_queue_update(self):
        if self.queue_update_callback:
            self.queue_update_callback()

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def connect(self, host="127.0.0.1", port=1883):
        self.host = host
        self.port = port
        self.log(f"Connecting to MQTT {self.host}:{self.port}...")
        try:
            self.client.connect(self.host, self.port, 60)
            self.client.loop_start()
            self.is_running = True
            return True
        except Exception as e:
            self.log(f"Connection failed: {e}")
            return False

    def disconnect(self):
        self.is_running = False
        self.client.loop_stop()
        self.client.disconnect()
        self.log("Disconnected.")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.log("Connected successfully.")
            self.client.subscribe(self.sub_topic)
            self.log(f"Subscribed to {self.sub_topic}")
            # Try to dispatch first item if any
            self.dispatch_next()
        else:
            self.log(f"Failed to connect, return code {rc}")

    def on_disconnect(self, client, userdata, rc):
        self.log("Disconnected from MQTT broker.")
        self.is_running = False

    def on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            if "id" in payload and "content" in payload:
                # Update current position continuously if available
                content = payload.get("content", {})
                if "CurLogicX" in content and "CurLogicY" in content:
                    with self.lock:
                        self.current_pos["x"] = content["CurLogicX"]
                        self.current_pos["y"] = content["CurLogicY"]

                # Check for completion event
                if payload["id"] == 20011 and content.get("EventId") == 4:
                    self.handle_completion(content)
        except json.JSONDecodeError:
            pass # Ignore malformed json
        except Exception as e:
            self.log(f"Error parsing message: {e}")

    def handle_completion(self, content):
        with self.lock:
            if not self.waiting_for_completion:
                return # Not waiting for anything

            result = content.get("OperationResult", -1)
            x = content.get("CurLogicX")
            y = content.get("CurLogicY")

            if result != 0:
                self.log(f"[ERROR] Task failed with OperationResult: {result}. Pausing queue.")
                self.is_paused = True
                self.waiting_for_completion = False
                return

            if self.expected_dest:
                if x != self.expected_dest["x"] or y != self.expected_dest["y"]:
                    self.log(f"[ERROR] Expected dest ({self.expected_dest['x']}, {self.expected_dest['y']}), but robot is at ({x}, {y}). Pausing queue.")
                    self.is_paused = True
                    self.waiting_for_completion = False
                    return

            # Success
            self.log(f"[+] Task completed at X:{x}, Y:{y}")
            self.waiting_for_completion = False
            self.queue_manager.pop_next() # Remove completed task
            self.last_sent_action = None

        self.notify_queue_update()
        # Dispatch next if not paused
        self.dispatch_next()

    def start_queue(self):
        with self.lock:
            self.is_paused = False
            if not self.waiting_for_completion:
                self.log("Queue started.")
        self.dispatch_next()

    def pause_queue(self):
        with self.lock:
            self.is_paused = True
            self.log("Queue paused.")

    def generate_payload(self, action):
        target_node = self.graph.nodes.get(action.node_id)
        if not target_node:
            self.log(f"Target node {action.node_id} not found in graph.")
            return None

        # Current position node ID
        start_node_id = self.graph.get_node_id_by_coords(self.current_pos["x"], self.current_pos["y"])
        if not start_node_id:
            # If current position not strictly in graph, start from closest or just use coords.
            # Assuming start_node_id can be derived. If not, just pathfind from closest node.
            # For simplicity, if robot is lost, fail.
            self.log(f"Robot current pos ({self.current_pos['x']}, {self.current_pos['y']}) not matching any node. Cannot pathfind.")
            return None

        path_ids = self.graph.find_path(start_node_id, action.node_id)
        if not path_ids:
            self.log(f"No path found from {start_node_id} to {action.node_id}.")
            return None

        link = []
        for pid in path_ids:
            node = self.graph.nodes[pid]
            link.append({"X": node["x"], "Y": node["y"], "Speed": 1000})

        op_type = 0
        pick_mode = 0
        if action.action_type == "PICK":
            op_type = 4
            pick_mode = 1
        elif action.action_type == "DROP":
            op_type = 4
            pick_mode = 2

        seq_no = int(time.time())

        payload = {
            "id": 1001,
            "content": {
                "OperationType": op_type,
                "PickMode": pick_mode,
                "GoodsSlotHeight": action.height,
                "SeqNo": seq_no,
                "LinkCounts": len(link),
                "Link": link,
                "StartX": self.current_pos["x"],
                "StartY": self.current_pos["y"],
                "EndX": target_node["x"],
                "EndY": target_node["y"]
            }
        }
        return payload

    def dispatch_next(self):
        with self.lock:
            if not self.is_running or self.is_paused or self.waiting_for_completion:
                return

            next_action = self.queue_manager.get_next()
            if not next_action:
                return # Queue empty

            payload = self.generate_payload(next_action)
            if not payload:
                self.log("Failed to generate payload for next action. Pausing queue.")
                self.is_paused = True
                return

            # Set expectations
            target_node = self.graph.nodes[next_action.node_id]
            self.expected_dest = {"x": target_node["x"], "y": target_node["y"]}
            self.waiting_for_completion = True
            self.last_sent_action = next_action

        # Publish
        try:
            self.client.publish(self.pub_topic, json.dumps(payload), qos=1)
            self.log(f"[>>>] Sending order SeqNo: {payload['content']['SeqNo']} - {next_action.action_type} to {next_action.node_id}")
        except Exception as e:
            self.log(f"Failed to publish: {e}")
            with self.lock:
                self.waiting_for_completion = False
                self.is_paused = True
