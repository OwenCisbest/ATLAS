import json
import math
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QBrush, QPen, QPainter, QImage
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QSpinBox,
    QPushButton, QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsItem, QLabel)
from app.core.types import ENTITY_TYPES

PALETTE = dict(zip(ENTITY_TYPES, ['#fbbf24', '#38bdf8', '#a78bfa', '#34d399', '#fb923c', '#f472b6', '#60a5fa']))


class Node(QGraphicsEllipseItem):
    def __init__(self, row, callback):
        super().__init__(-28, -28, 56, 56)
        self.row = row
        self.callback = callback
        self.edges = []
        self.setBrush(QBrush(QColor(PALETTE[row['entity_type']])))
        self.setPen(QPen(QColor('#dbeafe'), 2))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setToolTip(f"{row['title']}\n{row['entity_type']}\n{row['source_url']}")
        self.setData(0, row['id'])

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for edge, other in self.edges:
                edge.setLine(self.pos().x(), self.pos().y(), other.pos().x(), other.pos().y())
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        self.callback(self.row)
        super().mouseDoubleClickEvent(event)


class View(QGraphicsView):
    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1/1.15
        scale = self.transform().m11() * factor
        if 0.1 <= scale <= 8:
            self.scale(factor, factor)


class Graph(QWidget):
    inspect = Signal(object)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search = QLineEdit(placeholderText='Find a node…')
        self.kind = QComboBox()
        self.kind.addItems(['All types', *ENTITY_TYPES])
        self.confidence = QSpinBox()
        self.confidence.setRange(0, 100)
        self.confidence.setPrefix('Min grade: ')
        fit = QPushButton('Fit graph')
        collapse = QPushButton('Collapse / expand neighbors')
        for widget in (self.search, self.kind, self.confidence, fit, collapse):
            controls.addWidget(widget)
        layout.addLayout(controls)
        layout.addWidget(QLabel('Drag nodes • wheel to zoom • drag background to pan • double-click node or select edge for evidence'))
        layout.addWidget(QLabel('Green = confirmed • dashed amber = unverified • red = rejected • purple = user annotation'))
        self.scene = QGraphicsScene(self)
        self.view = View(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setBackgroundBrush(QColor('#101827'))
        layout.addWidget(self.view)
        self.nodes, self.edges, self.hidden = {}, [], set()
        self.search.textChanged.connect(self.filter)
        self.kind.currentTextChanged.connect(self.filter)
        self.confidence.valueChanged.connect(self.filter)
        fit.clicked.connect(lambda: self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio))
        collapse.clicked.connect(self.collapse)
        self.scene.selectionChanged.connect(self.selection)

    def selection(self):
        selected = self.scene.selectedItems()
        if selected and selected[0].data(1):
            self.inspect.emit(selected[0].data(1))

    def load(self, data):
        self.scene.clear()
        self.nodes, self.edges, self.hidden = {}, [], set()
        layout = json.loads(data['investigation']['layout'])
        for i, row in enumerate(data['evidence']):
            node = Node(row, self.inspect.emit)
            self.nodes[row['id']] = node
            self.scene.addItem(node)
            angle = i * 2 * math.pi / max(1, len(data['evidence']))
            pos = layout.get(row['id'], [260 * math.cos(angle), 260 * math.sin(angle)])
            node.setPos(*pos)
            label = self.scene.addText(row['title'][:36])
            label.setDefaultTextColor(QColor('#e2e8f0'))
            label.setParentItem(node)
            label.setPos(-65, 32)
        for row in data['relationships']:
            left, right = self.nodes.get(row['source_id']), self.nodes.get(row['target_id'])
            if not left or not right:
                continue
            color = '#c084fc' if row['annotation'] else {'confirmed': '#34d399', 'unverified': '#fbbf24', 'rejected': '#f87171'}[row['status']]
            pen = QPen(QColor(color), 3)
            if row['status'] == 'unverified':
                pen.setStyle(Qt.DashLine)
            edge = self.scene.addLine(left.x(), left.y(), right.x(), right.y(), pen)
            edge.setZValue(-1)
            edge.setFlag(QGraphicsItem.ItemIsSelectable)
            edge.setToolTip(row['label'] + '\n' + row['explanation'])
            edge.setData(1, row)
            left.edges.append((edge, right))
            right.edges.append((edge, left))
            self.edges.append((edge, row))
        self.filter()
        self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-60, -60, 60, 60), Qt.KeepAspectRatio)

    def filter(self, *_):
        for identifier, node in self.nodes.items():
            node.setVisible(identifier not in self.hidden and self.search.text().casefold() in node.row['title'].casefold()
                            and (self.kind.currentIndex() == 0 or node.row['entity_type'] == self.kind.currentText()))
        for edge, row in self.edges:
            edge.setVisible(self.nodes[row['source_id']].isVisible() and self.nodes[row['target_id']].isVisible()
                            and row['confidence'] >= self.confidence.value())

    def collapse(self):
        selected = [n for n in self.nodes.values() if n.isSelected()]
        if not selected:
            return
        for _, other in selected[0].edges:
            identifier = other.row['id']
            if identifier in self.hidden:
                self.hidden.remove(identifier)
            else:
                self.hidden.add(identifier)
        self.filter()

    def positions(self) -> str:
        return json.dumps({key: [node.x(), node.y()] for key, node in self.nodes.items()})

    def export(self, path: Path):
        bounds = self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        if path.suffix.lower() == '.svg':
            device = QSvgGenerator()
            device.setFileName(str(path))
            device.setSize(bounds.size().toSize())
            device.setViewBox(QRectF(0, 0, bounds.width(), bounds.height()))
        else:
            device = QImage(1600, 1000, QImage.Format_ARGB32)
            device.fill(QColor('#101827'))
        painter = QPainter(device)
        self.scene.render(painter, source=bounds)
        painter.end()
        if isinstance(device, QImage) and not device.save(str(path)):
            raise ValueError('Could not save graph image')
