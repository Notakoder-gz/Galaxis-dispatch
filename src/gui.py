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

class GraphViewer(QGraphicsView):
    node_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(self.renderHints()) # Antialiasing etc if needed
        self.nodes = {} # id -> item
        self.robot_item = None

    def update_robot(self, x, y):
        scale = 50
        px = x * scale
        py = y * scale

        if not self.robot_item:
            radius = 12
            self.robot_item = self.scene.addEllipse(
                -radius, -radius, radius*2, radius*2,
                QPen(Qt.black), QBrush(Qt.green)
            )
            self.robot_item.setZValue(10) # above nodes

        self.robot_item.setPos(px, py)

    def load_graph(self, graph):
        self.scene.clear()
        self.nodes.clear()

        # Scale for visualization
        scale = 50
        radius = 15

        # Draw edges
        for node_id, neighbors in graph.edges.items():
            n1 = graph.nodes[node_id]
            for neighbor_id in neighbors:
                n2 = graph.nodes[neighbor_id]
                # draw line
                line = self.scene.addLine(n1["x"]*scale, n1["y"]*scale,
                                          n2["x"]*scale, n2["y"]*scale,
                                          QPen(QColor(100, 100, 100), 2))
                line.setZValue(-1)

        # Draw nodes
        for node_id, data in graph.nodes.items():
            x = data["x"] * scale
            y = data["y"] * scale

            ellipse = self.scene.addEllipse(x - radius, y - radius, radius*2, radius*2,
                                            QPen(Qt.black), QBrush(Qt.blue))
            ellipse.setFlag(QGraphicsEllipseItem.ItemIsSelectable)
            ellipse.setData(0, node_id)

            text = self.scene.addText(node_id)
            text.setPos(x - radius, y - radius - 20)

            self.nodes[node_id] = ellipse

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item and isinstance(item, QGraphicsEllipseItem):
            node_id = item.data(0)
            self.node_clicked.emit(node_id)
        super().mousePressEvent(event)

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
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left Panel: Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        splitter.addWidget(left_panel)

        # 1. Connection
        conn_group = QGroupBox("MQTT Connection")
        conn_layout = QFormLayout(conn_group)
        self.host_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("1883")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addRow("Host:", self.host_input)
        conn_layout.addRow("Port:", self.port_input)
        conn_layout.addRow(self.connect_btn)
        left_layout.addWidget(conn_group)

        # 2. Graph Controls
        graph_group = QGroupBox("Graph Management")
        graph_layout = QVBoxLayout(graph_group)
        self.load_graph_btn = QPushButton("Load Graph JSON")
        self.load_graph_btn.clicked.connect(self.load_graph_dialog)
        graph_layout.addWidget(self.load_graph_btn)
        left_layout.addWidget(graph_group)

        # 3. Advanced Task Builder
        task_group = QGroupBox("Advanced Task Builder (Palletizing)")
        task_layout = QFormLayout(task_group)
        self.source_node_input = QLineEdit()
        self.target_node_input = QLineEdit()
        self.source_h_input = QSpinBox()
        self.source_h_input.setMaximum(10000)
        self.base_h_input = QSpinBox()
        self.base_h_input.setMaximum(10000)
        self.step_h_input = QSpinBox()
        self.step_h_input.setMaximum(10000)
        self.count_input = QSpinBox()
        self.count_input.setValue(1)

        task_layout.addRow("Source Node:", self.source_node_input)
        task_layout.addRow("Source Height:", self.source_h_input)
        task_layout.addRow("Target Node:", self.target_node_input)
        task_layout.addRow("Base Drop Height:", self.base_h_input)
        task_layout.addRow("Height Step:", self.step_h_input)
        task_layout.addRow("Count:", self.count_input)

        self.add_macro_btn = QPushButton("Add Palletizing Job")
        self.add_macro_btn.clicked.connect(self.add_palletizing_job)
        task_layout.addRow(self.add_macro_btn)

        # Quick Actions
        self.quick_node_input = QLineEdit()
        self.quick_node_input.setPlaceholderText("Click node on map...")
        self.quick_move_btn = QPushButton("Quick Move to Node")
        self.quick_move_btn.clicked.connect(self.add_quick_move)
        task_layout.addRow("Target Node:", self.quick_node_input)
        task_layout.addRow(self.quick_move_btn)

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

        # Utilities
        util_group = QGroupBox("Utilities")
        util_layout = QVBoxLayout(util_group)
        self.preview_btn = QPushButton("Preview Next Order JSON")
        self.preview_btn.clicked.connect(self.preview_next_order)
        util_layout.addWidget(self.preview_btn)
        left_layout.addWidget(util_group)

        # Queue Control
        qc_group = QGroupBox("Queue Controls")
        qc_layout = QHBoxLayout(qc_group)
        self.start_q_btn = QPushButton("Start/Resume")
        self.start_q_btn.clicked.connect(self.dispatcher.start_queue)
        self.pause_q_btn = QPushButton("Pause")
        self.pause_q_btn.clicked.connect(self.dispatcher.pause_queue)
        self.clear_q_btn = QPushButton("Clear")
        self.clear_q_btn.clicked.connect(self.clear_queue)
        qc_layout.addWidget(self.start_q_btn)
        qc_layout.addWidget(self.pause_q_btn)
        qc_layout.addWidget(self.clear_q_btn)
        left_layout.addWidget(qc_group)

        # Center Panel: Visuals & Logs
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        splitter.addWidget(center_panel)

        # Visual Map
        self.graph_viewer = GraphViewer()
        self.graph_viewer.node_clicked.connect(self.on_node_clicked)

        map_header = QHBoxLayout()
        map_header.addWidget(QLabel("Visual Map"))
        self.telemetry_label = QLabel("Robot: Idle | Battery: --%")
        self.telemetry_label.setAlignment(Qt.AlignRight)
        map_header.addWidget(self.telemetry_label)

        center_layout.addLayout(map_header)
        center_layout.addWidget(self.graph_viewer, stretch=2)

        # Queue List
        center_layout.addWidget(QLabel("Task Queue"))
        self.queue_list = QListWidget()
        center_layout.addWidget(self.queue_list, stretch=1)

        # Log Console
        center_layout.addWidget(QLabel("Log Console"))
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        center_layout.addWidget(self.log_console, stretch=1)

        splitter.setSizes([300, 700])

    @Slot(float, float, int, int)
    def update_telemetry_ui(self, x, y, battery, status):
        status_str = "Moving/Executing" if status == 2 else "Idle"
        self.telemetry_label.setText(f"Robot: {status_str} | Battery: {battery}% | X:{x:.1f} Y:{y:.1f}")
        self.graph_viewer.update_robot(x, y)

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
            if self.dispatcher.connect(host, port):
                self.connect_btn.setText("Disconnect")
        else:
            self.dispatcher.disconnect()
            self.connect_btn.setText("Connect")

    def load_graph_dialog(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Graph JSON", "", "JSON Files (*.json)")
        if file_name:
            try:
                self.graph.load_from_json(file_name)
                self.graph_viewer.load_graph(self.graph)
                self.signals.log_msg.emit(f"Graph loaded from {file_name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load graph:\n{e}")

    @Slot(str)
    def on_node_clicked(self, node_id):
        # Auto fill the quick node input or other logic
        self.quick_node_input.setText(node_id)
        if not self.source_node_input.text():
            self.source_node_input.setText(node_id)
        elif not self.target_node_input.text():
            self.target_node_input.setText(node_id)
        self.signals.log_msg.emit(f"Node selected: {node_id}")

    def add_palletizing_job(self):
        src = self.source_node_input.text()
        tgt = self.target_node_input.text()
        if not src or not tgt:
            QMessageBox.warning(self, "Warning", "Please specify source and target nodes.")
            return

        job = PalletizingJob(
            src, tgt,
            self.source_h_input.value(),
            self.base_h_input.value(),
            self.step_h_input.value(),
            self.count_input.value()
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

    def clear_queue(self):
        self.queue_manager.clear()
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit("Queue cleared.")

    @Slot()
    def update_queue_ui(self):
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
