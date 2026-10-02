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
        self.telemetry_update_callback = None

        self.last_sent_action = None
        self.waiting_for_completion = False

        self.battery = 0
        self.task_mode = 0 # 0=Idle, 2=Moving/Executing

        # Thread safety lock
        self.lock = threading.Lock()

    def set_log_callback(self, cb):
        self.log_callback = cb

    def set_queue_update_callback(self, cb):
        self.queue_update_callback = cb

    def set_telemetry_update_callback(self, cb):
        self.telemetry_update_callback = cb

    def notify_queue_update(self):
        if self.queue_update_callback:
            self.queue_update_callback()

    def notify_telemetry_update(self):
        if self.telemetry_update_callback:
            self.telemetry_update_callback(self.current_pos["x"], self.current_pos["y"], self.battery, self.task_mode)

    def log(self, msg):
        if self.log_callback:
            self.log_callback(msg)
        else:
            print(msg)

    def connect(self, host="127.0.0.1", port=1883, pub_topic="/wcs_server/30", sub_topic="/agv_robot/status"):
        self.host = host
        self.port = port
        self.pub_topic = pub_topic
        self.sub_topic = sub_topic
        self.log(f"Connecting to MQTT {self.host}:{self.port} (Pub: {self.pub_topic}, Sub: {self.sub_topic})...")
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
                content = payload.get("content", {})

                telemetry_updated = False

                # Update current position continuously if available (or via telemetry)
                if payload["id"] == 20020 or payload["id"] == 20010:
                    if "CurX" in content and "CurY" in content:
                        with self.lock:
                            self.current_pos["x"] = content["CurX"]
                            self.current_pos["y"] = content["CurY"]
                            telemetry_updated = True

                if "CurLogicX" in content and "CurLogicY" in content:
                    with self.lock:
                        self.current_pos["x"] = content["CurLogicX"]
                        self.current_pos["y"] = content["CurLogicY"]
                        telemetry_updated = True

                # Battery and TaskMode telemetry
                if payload["id"] == 20100:
                    with self.lock:
                        if "Battery" in content:
                            self.battery = content["Battery"]
                            telemetry_updated = True
                        if "TaskMode" in content:
                            self.task_mode = content["TaskMode"]
                            telemetry_updated = True

                if telemetry_updated:
                    self.notify_telemetry_update()

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
                if self.last_sent_action:
                    self.last_sent_action.status = "failed"
                self.notify_queue_update()
                return

            if self.expected_dest:
                if x != self.expected_dest["x"] or y != self.expected_dest["y"]:
                    self.log(f"[ERROR] Expected dest ({self.expected_dest['x']}, {self.expected_dest['y']}), but robot is at ({x}, {y}). Pausing queue.")
                    self.is_paused = True
                    self.waiting_for_completion = False
                    if self.last_sent_action:
                        self.last_sent_action.status = "failed"
                    self.notify_queue_update()
                    return

            # Success
            self.log(f"[+] Task completed at X:{x}, Y:{y}")
            self.waiting_for_completion = False
            completed_action = self.queue_manager.pop_next() # Remove completed task
            if completed_action:
                completed_action.status = "completed"
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
        target_x, target_y = 0, 0
        link = []

        if action.manual_coords:
            target_x = action.manual_coords["x"]
            target_y = action.manual_coords["y"]
            # Graph-less mode: single node link array to target
            link.append({"X": target_x, "Y": target_y, "Speed": 1000})
        else:
            target_node = self.graph.nodes.get(action.node_id)
            if not target_node:
                self.log(f"Target node {action.node_id} not found in graph.")
                return None
            target_x = target_node["x"]
            target_y = target_node["y"]

            if not self.graph.nodes:
                link.append({"X": target_x, "Y": target_y, "Speed": 1000})
            else:
                start_node_id = self.graph.get_node_id_by_coords(self.current_pos["x"], self.current_pos["y"])
                if not start_node_id:
                    self.log(f"Robot current pos ({self.current_pos['x']}, {self.current_pos['y']}) not matching any node. Cannot pathfind.")
                    return None

                path_ids = self.graph.find_path(start_node_id, action.node_id)
                if not path_ids:
                    self.log(f"No path found from {start_node_id} to {action.node_id}.")
                    return None

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
            "id": 10010,
            "content": {
                "SeqNo": seq_no,
                "OperationType": op_type,
                "StartX": self.current_pos["x"],
                "StartY": self.current_pos["y"],
                "EndX": target_x,
                "EndY": target_y,
                "LinkCounts": len(link),
                "Link": link
            }
        }

        if op_type == 4:
            payload["content"]["PickMode"] = pick_mode
            payload["content"]["GoodsSlotHeight"] = action.height
            payload["content"]["GoodsSlotDirection"] = 0

        return payload

    def send_custom_payload(self, json_str):
        if not self.is_running:
            self.log("Cannot send custom payload: Not connected.")
            return False

        try:
            payload = json.loads(json_str)
            self.client.publish(self.pub_topic, json.dumps(payload), qos=1)
            self.log(f"[>>>] Sent Custom Payload (ID: {payload.get('id')})")
            return True
        except Exception as e:
            self.log(f"Failed to send custom payload: {e}")
            return False

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
            if next_action.manual_coords:
                self.expected_dest = {"x": next_action.manual_coords["x"], "y": next_action.manual_coords["y"]}
            else:
                target_node = self.graph.nodes[next_action.node_id]
                self.expected_dest = {"x": target_node["x"], "y": target_node["y"]}

            self.waiting_for_completion = True
            self.last_sent_action = next_action
            next_action.status = "executing"
            self.notify_queue_update()

        # Publish
        try:
            self.client.publish(self.pub_topic, json.dumps(payload), qos=1)
            self.log(f"[>>>] Sending order SeqNo: {payload['content']['SeqNo']} - {next_action.action_type} to {next_action.node_id}")
        except Exception as e:
            self.log(f"Failed to publish: {e}")
            with self.lock:
                self.waiting_for_completion = False
                self.is_paused = True
