"""主程序入口"""

import sys
from PySide6.QtWidgets import QApplication
from ui import AimWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = AimWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
