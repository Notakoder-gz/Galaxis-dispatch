import sys
from PySide6.QtWidgets import QApplication
from src.gui import MainWindow

def test():
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    win = MainWindow()

    # Verify reset AMR method exists and works
    win.reset_amr()

    # Test Palletizing with manual coords
    win.use_manual_coords_cb.setChecked(True)
    win.source_node_input.setText("1,2")
    win.target_node_input.setText("3,4")
    win.add_palletizing_job()

    assert len(win.queue_manager.get_queue()) == 4 # default count 1 -> 4 actions
    print("GUI updates sanity checked.")

test()
