import sys
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QGroupBox, QFormLayout, QSpinBox, QListWidget,
                               QTextEdit, QSplitter, QFileDialog, QMessageBox,
                               QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
                               QGraphicsLineItem, QGraphicsTextItem)
from PySide6.QtCore import Qt, Signal, Slot, QObject
from PySide6.QtGui import QPen, QBrush, QColor, QFont

from src.graph import Graph
from src.jobs import QueueManager, Action, PalletizingJob
from src.mqtt_dispatcher import Dispatcher

class Signals(QObject):
    log_msg = Signal(str)
    queue_updated = Signal()
    telemetry_updated = Signal(float, float, int, int) # x, y, battery, status

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mini-RCS KUKA Galaxis AMR")
        self.resize(1000, 700)

        self.graph = Graph()
        self.queue_manager = QueueManager()
        self.dispatcher = Dispatcher(self.graph, self.queue_manager)

        self.signals = Signals()
        self.signals.log_msg.connect(self.append_log)
        self.signals.queue_updated.connect(self.update_queue_ui)
        self.signals.telemetry_updated.connect(self.update_telemetry_ui)
        self.dispatcher.set_log_callback(lambda msg: self.signals.log_msg.emit(msg))
        self.dispatcher.set_queue_update_callback(lambda: self.signals.queue_updated.emit())
        self.dispatcher.set_telemetry_update_callback(lambda x, y, b, s: self.signals.telemetry_updated.emit(x, y, b, s))

        self.setup_ui()

    def setup_ui(self):
        self.setup_menu()

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter, stretch=1)

        # Left Panel: Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)

        self.setup_panels(splitter, left_layout)

    def setup_menu(self):
        menubar = self.menuBar()
        help_menu = menubar.addMenu("Help")

        instructions_action = help_menu.addAction("Instructions")
        instructions_action.triggered.connect(self.show_instructions)

    def setup_panels(self, splitter, left_layout):
        # 1. Connection
        conn_group = QGroupBox("MQTT Connection")
        conn_layout = QFormLayout(conn_group)
        self.host_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("1883")
        self.pub_topic_input = QLineEdit("/wcs_server/30")
        self.sub_topic_input = QLineEdit("/agv_robot/status")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addRow("Host:", self.host_input)
        conn_layout.addRow("Port:", self.port_input)
        conn_layout.addRow("Pub Topic:", self.pub_topic_input)
        conn_layout.addRow("Sub Topic:", self.sub_topic_input)
        conn_layout.addRow(self.connect_btn)
        left_layout.addWidget(conn_group)

        from PySide6.QtWidgets import QCheckBox

        # 2. Graph Controls
        graph_group = QGroupBox("Map & Nodes")
        graph_layout = QVBoxLayout(graph_group)
        self.load_graph_btn = QPushButton("Load KUKA Map JSON")
        self.load_graph_btn.clicked.connect(self.load_graph_dialog)
        graph_layout.addWidget(self.load_graph_btn)
        left_layout.addWidget(graph_group)

        # 3. Advanced Task Builder
        task_group = QGroupBox("Advanced Task Builder (Palletizing)")
        task_layout = QFormLayout(task_group)

        self.use_manual_coords_cb = QCheckBox("Use Manual Coordinates (Graph-less)")
        task_layout.addRow(self.use_manual_coords_cb)

        self.source_node_input = QLineEdit()
        self.target_node_input = QLineEdit()
        self.source_node_input.setPlaceholderText("Node ID or 'X,Y'")
        self.target_node_input.setPlaceholderText("Node ID or 'X,Y'")

        self.source_h_input = QSpinBox()
        self.source_h_input.setMaximum(10000)
        self.base_h_input = QSpinBox()
        self.base_h_input.setMaximum(10000)
        self.step_h_input = QSpinBox()
        self.step_h_input.setMaximum(10000)
        self.count_input = QSpinBox()
        self.count_input.setValue(1)

        task_layout.addRow("Source:", self.source_node_input)
        task_layout.addRow("Source Height:", self.source_h_input)
        task_layout.addRow("Target:", self.target_node_input)
        task_layout.addRow("Base Drop Height:", self.base_h_input)
        task_layout.addRow("Height Step:", self.step_h_input)
        task_layout.addRow("Count:", self.count_input)

        self.add_macro_btn = QPushButton("Add Palletizing Job")
        self.add_macro_btn.clicked.connect(self.add_palletizing_job)
        task_layout.addRow(self.add_macro_btn)

        left_layout.addWidget(task_group)

        # Manual Task Entry
        manual_group = QGroupBox("Manual Task (Graph-less)")
        manual_layout = QFormLayout(manual_group)

        self.manual_x = QSpinBox()
        self.manual_y = QSpinBox()
        self.manual_h = QSpinBox()
        self.manual_h.setMaximum(10000)

        btn_layout = QHBoxLayout()
        self.manual_move_btn = QPushButton("Move")
        self.manual_move_btn.clicked.connect(self.add_manual_move)
        self.manual_pick_btn = QPushButton("Pick")
        self.manual_pick_btn.clicked.connect(self.add_manual_pick)
        self.manual_drop_btn = QPushButton("Drop")
        self.manual_drop_btn.clicked.connect(self.add_manual_drop)

        btn_layout.addWidget(self.manual_move_btn)
        btn_layout.addWidget(self.manual_pick_btn)
        btn_layout.addWidget(self.manual_drop_btn)

        manual_layout.addRow("Target X:", self.manual_x)
        manual_layout.addRow("Target Y:", self.manual_y)
        manual_layout.addRow("Height (for Pick/Drop):", self.manual_h)
        manual_layout.addRow(btn_layout)
        left_layout.addWidget(manual_group)

        # Utilities & Custom Orders
        util_group = QGroupBox("Utilities & Custom Payload")
        util_layout = QVBoxLayout(util_group)
        self.preview_btn = QPushButton("Preview Next Action Payload")
        self.preview_btn.clicked.connect(self.preview_next_order)
        util_layout.addWidget(self.preview_btn)

        self.custom_json_input = QTextEdit()
        self.custom_json_input.setPlaceholderText("Paste custom JSON order here...")
        self.custom_json_input.setMaximumHeight(80)
        self.send_custom_btn = QPushButton("Send Custom JSON")
        self.send_custom_btn.clicked.connect(self.send_custom_order)

        self.reset_amr_btn = QPushButton("Reset AMR Error (id: 10120)")
        self.reset_amr_btn.clicked.connect(self.reset_amr)

        util_layout.addWidget(self.custom_json_input)
        util_layout.addWidget(self.send_custom_btn)
        util_layout.addWidget(self.reset_amr_btn)
        left_layout.addWidget(util_group)

        # Raw JSON Task
        raw_group = QGroupBox("Raw JSON Sequence Item")
        raw_layout = QVBoxLayout(raw_group)
        self.raw_json_input = QTextEdit()
        self.raw_json_input.setPlaceholderText("Paste raw JSON for ONE step here...")
        self.raw_json_input.setMaximumHeight(80)
        self.add_raw_btn = QPushButton("Add Raw JSON to Queue")
        self.add_raw_btn.clicked.connect(self.add_raw_json_task)
        raw_layout.addWidget(self.raw_json_input)
        raw_layout.addWidget(self.add_raw_btn)
        left_layout.addWidget(raw_group)

        # Right Panel: Queue & Logs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        splitter.addWidget(right_panel)

        # Queue Control & Telemetry Header
        header_layout = QHBoxLayout()
        self.telemetry_label = QLabel("Robot: Idle | Battery: --%")
        self.telemetry_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self.telemetry_label)

        self.loop_cb = QCheckBox("Loop Queue")
        self.loop_cb.toggled.connect(self.dispatcher.set_loop_queue)
        header_layout.addWidget(self.loop_cb, alignment=Qt.AlignRight)
        right_layout.addLayout(header_layout)

        qc_group = QGroupBox("Queue Controls")
        qc_layout = QHBoxLayout(qc_group)
        self.start_q_btn = QPushButton("Start/Resume")
        self.start_q_btn.clicked.connect(self.dispatcher.start_queue)
        self.pause_q_btn = QPushButton("Pause")
        self.pause_q_btn.clicked.connect(self.dispatcher.pause_queue)
        self.clear_q_btn = QPushButton("Clear Queue")
        self.clear_q_btn.clicked.connect(self.clear_queue)
        qc_layout.addWidget(self.start_q_btn)
        qc_layout.addWidget(self.pause_q_btn)
        qc_layout.addWidget(self.clear_q_btn)
        right_layout.addWidget(qc_group)

        # Queue List
        queue_header_layout = QHBoxLayout()
        queue_header_layout.addWidget(QLabel("Task Queue"))
        self.q_up_btn = QPushButton("▲")
        self.q_up_btn.clicked.connect(lambda: self.move_q_item(-1))
        self.q_down_btn = QPushButton("▼")
        self.q_down_btn.clicked.connect(lambda: self.move_q_item(1))
        self.q_del_btn = QPushButton("Delete Selected")
        self.q_del_btn.clicked.connect(self.delete_q_item)
        queue_header_layout.addWidget(self.q_up_btn)
        queue_header_layout.addWidget(self.q_down_btn)
        queue_header_layout.addWidget(self.q_del_btn)

        right_layout.addLayout(queue_header_layout)
        self.queue_list = QListWidget()
        right_layout.addWidget(self.queue_list, stretch=2)

        # Log Console
        right_layout.addWidget(QLabel("Log Console"))
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        right_layout.addWidget(self.log_console, stretch=1)

        splitter.setSizes([400, 600])

    @Slot(float, float, int, int)
    def update_telemetry_ui(self, x, y, battery, status):
        status_str = "Moving/Executing" if status == 2 else "Idle"
        self.telemetry_label.setText(f"Robot: {status_str} | Battery: {battery}% | X:{x:.1f} Y:{y:.1f}")

    @Slot(str)
    def append_log(self, msg):
        self.log_console.append(msg)
        # Scroll to bottom
        sb = self.log_console.verticalScrollBar()
        sb.setValue(sb.maximum())

    def toggle_connection(self):
        if not self.dispatcher.is_running:
            host = self.host_input.text()
            port = int(self.port_input.text())
            pub = self.pub_topic_input.text()
            sub = self.sub_topic_input.text()
            if self.dispatcher.connect(host, port, pub, sub):
                self.connect_btn.setText("Disconnect")
        else:
            self.dispatcher.disconnect()
            self.connect_btn.setText("Connect")

    def show_instructions(self):
        from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("Mini-RCS Instructions")
        dlg.resize(600, 500)

        layout = QVBoxLayout(dlg)

        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(self.get_instructions_html())
        layout.addWidget(tb)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.exec()

    def get_instructions_html(self):
        return """
        <h2>Mini-RCS Operator Guide</h2>

        <h3>1. Connection & Setup</h3>
        <p>Enter the IP address of the robot (or SSH tunnel) and the correct MQTT port. If your robot uses different MQTT topics for status and server commands, you can edit them here. Click <b>Connect</b> to start listening to the robot's telemetry.</p>

        <h3>2. Map & Nodes</h3>
        <p>By default, the application runs in "Graph-less" mode. If you want to dispatch the robot using Node IDs (e.g. Node "11"), you must click <b>Load KUKA Map JSON</b> and select the map dump from the robot. The system will parse the <code>logicX</code>, <code>logicY</code>, and paths to enable A* routing.</p>

        <h3>3. Adding Tasks to the Queue</h3>
        <p>The system is a sequential task dispatcher. You build a list of tasks, and it executes them one-by-one:</p>
        <ul>
            <li><b>Manual Task (Graph-less):</b> Send the robot to explicit X/Y logical coordinates. You can choose Move, Pick, or Drop.</li>
            <li><b>Advanced Palletizing:</b> Automatically generates a sequence of "Move -> Pick -> Move -> Drop" tasks to stack items. You can use standard Node IDs (if a map is loaded) or check the "Use Manual Coordinates" box to provide raw X,Y pairs (like "0,1").</li>
            <li><b>Raw JSON:</b> Paste a completely custom JSON payload (e.g., from a test dump) to add it as a step in the queue. The dispatcher will inject the correct <code>SeqNo</code> automatically.</li>
        </ul>

        <h3>4. Queue Controls</h3>
        <ul>
            <li><b>Start/Resume:</b> Begins publishing the top-most pending task to the robot.</li>
            <li><b>Pause:</b> Halts the queue. The currently executing task will finish, but the next task will not be sent.</li>
            <li><b>Edit Queue:</b> Use the ▲, ▼, and Delete buttons to modify pending tasks without having to clear the whole queue.</li>
            <li><b>Loop Queue:</b> When checked, completed tasks are moved back to the bottom of the queue instead of being deleted, allowing infinite test loops.</li>
        </ul>

        <h3>5. Error Handling & Utilities</h3>
        <ul>
            <li><b>Preview Next Action:</b> Shows the exact JSON payload that will be sent for the next task in the queue.</li>
            <li><b>Reset AMR Error (10120):</b> If the robot rejects an order or enters an error state, click this. It bypasses the queue, instantly sends a Reset Payload (SeqNo: 0), and clears the "Failed" task from the queue so you can safely click Resume.</li>
            <li><b>Send Custom JSON:</b> Instantly publishes the provided raw JSON payload directly to the robot, completely bypassing the queue.</li>
        </ul>
        """

    def load_graph_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        file_name, _ = QFileDialog.getOpenFileName(self, "Open KUKA Map JSON", "", "JSON Files (*.json)")
        if file_name:
            try:
                self.dispatcher.graph.load_from_json(file_name)
                self.signals.log_msg.emit(f"Map loaded from {file_name}. Nodes available: {len(self.dispatcher.graph.nodes)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load map:\n{e}")

    def add_raw_json_task(self):
        json_str = self.raw_json_input.toPlainText()
        if not json_str.strip():
            return

        try:
            payload = json.loads(json_str)
            from src.jobs import RawJSONAction
            self.queue_manager.add_action(RawJSONAction(payload))
            self.signals.queue_updated.emit()
            self.signals.log_msg.emit("Added Raw JSON to queue.")
            self.raw_json_input.clear()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Invalid JSON:\n{e}")

    def add_palletizing_job(self):
        src = self.source_node_input.text()
        tgt = self.target_node_input.text()
        if not src or not tgt:
            QMessageBox.warning(self, "Warning", "Please specify source and target.")
            return

        use_manual = self.use_manual_coords_cb.isChecked()
        src_coords = None
        tgt_coords = None

        if use_manual:
            try:
                sx, sy = map(int, src.split(","))
                tx, ty = map(int, tgt.split(","))
                src_coords = {"x": sx, "y": sy}
                tgt_coords = {"x": tx, "y": ty}
            except ValueError:
                QMessageBox.warning(self, "Warning", "Manual coords must be in 'X,Y' format (e.g. '0,1').")
                return

        job = PalletizingJob(
            src if not use_manual else "manual_src",
            tgt if not use_manual else "manual_tgt",
            self.source_h_input.value(),
            self.base_h_input.value(),
            self.step_h_input.value(),
            self.count_input.value(),
            manual_src_coords=src_coords,
            manual_tgt_coords=tgt_coords
        )
        self.queue_manager.add_macro_job(job)
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit(f"Added palletizing job: {job.count} items from {src} to {tgt}")

    def add_quick_move(self):
        tgt = self.quick_node_input.text()
        if not tgt:
            return
        self.queue_manager.add_action(Action("MOVE", tgt))
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit(f"Added quick move to {tgt}")

    def add_manual_move(self):
        x = self.manual_x.value()
        y = self.manual_y.value()
        action = Action("MOVE", "manual", manual_coords={"x": x, "y": y})
        self.queue_manager.add_action(action)
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit(f"Added manual Move to X:{x}, Y:{y}")

    def add_manual_pick(self):
        x = self.manual_x.value()
        y = self.manual_y.value()
        h = self.manual_h.value()
        action = Action("PICK", "manual", height=h, manual_coords={"x": x, "y": y})
        self.queue_manager.add_action(action)
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit(f"Added manual Pick to X:{x}, Y:{y}, H:{h}")

    def add_manual_drop(self):
        x = self.manual_x.value()
        y = self.manual_y.value()
        h = self.manual_h.value()
        action = Action("DROP", "manual", height=h, manual_coords={"x": x, "y": y})
        self.queue_manager.add_action(action)
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit(f"Added manual Drop to X:{x}, Y:{y}, H:{h}")

    def send_custom_order(self):
        json_str = self.custom_json_input.toPlainText()
        if not json_str.strip():
            return
        if self.dispatcher.send_custom_payload(json_str):
            self.signals.log_msg.emit("Custom payload sent successfully.")
        else:
            QMessageBox.warning(self, "Error", "Failed to send custom payload. Check JSON validity and connection.")

    def reset_amr(self):
        reset_payload = '{"id": 10120, "content": {"SeqNo": 0}}'
        if self.dispatcher.send_custom_payload(reset_payload):
            self.signals.log_msg.emit("Sent AMR Reset command (10120).")
            # Clear dispatcher waiting state to allow queue to resume if user clicks Start/Resume
            with self.dispatcher.lock:
                self.dispatcher.waiting_for_completion = False
                # Discard the failed item entirely from dispatcher state so queue can proceed normally
                if self.dispatcher.last_sent_action:
                    # Pop the failed item from the actual queue so it doesn't retry infinitely
                    self.queue_manager.pop_next()
                self.dispatcher.last_sent_action = None
            self.signals.queue_updated.emit()
        else:
            QMessageBox.warning(self, "Error", "Failed to send reset command.")

    def preview_next_order(self):
        next_action = self.queue_manager.get_next()
        if not next_action:
            QMessageBox.information(self, "Preview", "Queue is empty.")
            return

        payload = self.dispatcher.generate_payload(next_action)
        if not payload:
            QMessageBox.warning(self, "Error", "Failed to generate payload. Check map/graph or coords.")
            return

        formatted_json = json.dumps(payload, indent=4)
        QMessageBox.information(self, "Order Preview", formatted_json)

    def move_q_item(self, offset):
        idx = self._get_selected_queue_index()
        if idx is not None:
            new_idx = self.queue_manager.move_action(idx, offset)
            self.signals.queue_updated.emit()

            # Select new index taking into account the extra row for executing task if present
            visual_offset = 1 if self.dispatcher.last_sent_action else 0
            self.queue_list.setCurrentRow(new_idx + visual_offset)

    def delete_q_item(self):
        idx = self._get_selected_queue_index()
        if idx is not None:
            self.queue_manager.remove_action(idx)
            self.signals.queue_updated.emit()

    def _get_selected_queue_index(self):
        row = self.queue_list.currentRow()
        if row < 0:
            return None
        # The visual list row mapping perfectly aligns with the underlying queue manager list.
        # However, we must prevent edits to the currently executing task if it is visibly displayed at row 0.
        if self.dispatcher.last_sent_action and self.dispatcher.last_sent_action.status != "completed":
            if row == 0:
                QMessageBox.warning(self, "Warning", "Cannot modify the currently executing task.")
                return None
            return row
        return row

    def clear_queue(self):
        self.queue_manager.clear()
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit("Queue cleared.")

    @Slot()
    def update_queue_ui(self):
        if self.dispatcher.is_paused:
            self.pause_q_btn.setText("Queue is PAUSED")
            self.pause_q_btn.setStyleSheet("background-color: orange;")
        else:
            self.pause_q_btn.setText("Pause")
            self.pause_q_btn.setStyleSheet("")

        self.queue_list.clear()

        # If there is a last sent action, always show it at the top.
        # But we must only show "completed" temporarily until next queue refresh to avoid dead code
        # However, to meet the requirements correctly, we just show it.
        if self.dispatcher.last_sent_action:
            act = self.dispatcher.last_sent_action
            if act.status != "completed": # Completed tasks are cleared immediately by pop_next usually, but handle just in case
                item = self.queue_list.addItem(f"[*] {act}")
                list_item = self.queue_list.item(self.queue_list.count()-1)
                if act.status == "executing":
                    list_item.setForeground(QColor(0, 0, 255)) # Blue
                    list_item.setBackground(QColor(230, 230, 255))
                elif act.status == "failed":
                    list_item.setForeground(QColor(255, 0, 0)) # Red
                    list_item.setBackground(QColor(255, 230, 230))

        # Show pending items
        for i, action in enumerate(self.queue_manager.get_queue()):
            # Only display if it's not the exact instance that is currently executing (just to be safe against double rendering)
            if action != self.dispatcher.last_sent_action:
                self.queue_list.addItem(f"{i}: {action}")
                list_item = self.queue_list.item(self.queue_list.count()-1)
                list_item.setForeground(QColor(100, 100, 100)) # Gray for pending

    def closeEvent(self, event):
        self.dispatcher.disconnect()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
