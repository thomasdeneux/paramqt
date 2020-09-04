
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt

# taken from the example: https://doc.qt.io/qt-5/qtwidgets-layouts-flowlayout-example.html
class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, margin=-1, h_spacing=0, v_spacing=0):
        # type: (QtWidgets.QWidget, int, int, int) -> None
        super(FlowLayout, self).__init__(parent)
        self.h_spacing = max(h_spacing, 0)
        self.v_spacing = max(v_spacing, 0)
        self.setContentsMargins(margin, margin, margin, margin)

        self.items = []  # type: [QtWidgets.QLayoutItem]

    def addItem(self, item):
        # type: (QtWidgets.QLayoutItem) -> None
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        try:
            return self.items[i]
        except IndexError:
            return None

    def takeAt(self, i):
        try:
            return self.items.pop(i)
        except IndexError:
            return None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def sizeParams(self, width):
        # type: (int) -> QtCore.QSize
        return self.doLayout(QtCore.QRect(0, 0, width, 0), test_only=True)

    def heightForWidth(self, width):
        # type: (int) -> int
        return self.sizeParams(width).height()

    def setGeometry(self, rect):
        super(FlowLayout, self).setGeometry(rect)
        self.doLayout(rect)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())

        margins = self.contentsMargins()
        return size + QtCore.QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    # The main function
    def doLayout(self, rect, test_only=False):
        # type: (QtCore.QRect, bool) -> QtCore.QSize
        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(+left, +top, -right, -bottom)
        x = effective_rect.x()
        y = effective_rect.y()
        max_x = x
        line_height = 0

        for item in self.items:  # type: QtWidgets.QLayout
            size = item.sizeHint()
            x_offset = size.width() + self.h_spacing
            next_x = x + x_offset

            # for some reason right() returns x() + width() - 1
            if next_x - self.h_spacing > effective_rect.right() + 1 and line_height > 0:
                max_x = max(max_x, x - self.h_spacing)
                x = effective_rect.x()
                y += line_height + self.v_spacing
                next_x = x + x_offset
                line_height = 0

            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), size))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        max_x = max(max_x, x - self.h_spacing)
        return QtCore.QSize(max_x - rect.x() + right,
                            y + line_height - rect.y() + bottom)

