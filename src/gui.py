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

class GraphViewer(QGraphicsView):
    node_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHint(self.renderHints()) # Antialiasing etc if needed
        self.nodes = {} # id -> item

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
        self.dispatcher.set_log_callback(lambda msg: self.signals.log_msg.emit(msg))
        self.dispatcher.set_queue_update_callback(lambda: self.signals.queue_updated.emit())

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
        self.quick_move_btn = QPushButton("Quick Move")
        self.quick_move_btn.clicked.connect(self.add_quick_move)
        task_layout.addRow("Target:", self.quick_node_input)
        task_layout.addRow(self.quick_move_btn)

        left_layout.addWidget(task_group)

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
        center_layout.addWidget(QLabel("Visual Map"))
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

    def clear_queue(self):
        self.queue_manager.clear()
        self.signals.queue_updated.emit()
        self.signals.log_msg.emit("Queue cleared.")

    @Slot()
    def update_queue_ui(self):
        self.queue_list.clear()
        for i, action in enumerate(self.queue_manager.get_queue()):
            self.queue_list.addItem(f"{i}: {action}")

    def closeEvent(self, event):
        self.dispatcher.disconnect()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
