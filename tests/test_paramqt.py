from paramqt import *

TEST_INSTANCE = True


# define dummy 'translation' functions
def to_upper_case(s: str):
    if s is None:
        return None
    else:
        return s.upper()


def caesar_cipher(s: str):
    if s is None:
        return None
    x = np.frombuffer(bytes(s, 'ascii'), dtype='uint8').copy()
    index_up = np.logical_or(np.logical_and(97 <= x, x < 122),
                             np.logical_and(65 <= x, x < 90))
    index_z = (x == 122)
    index_Z = (x == 90)
    x[index_up] += 1  # a-y -> b-z, A-Y -> B-Z
    x[index_z] = 97  # z -> a
    x[index_Z] = 65  # Z -> A
    return bytes(x).decode()


# General parameters
class GeneralPar(GParameterized):
    show_expert = GBoolean(True, label='Show expert parameters')
    translation = GObjectSelector(None, allow_None=True,
                                  objects={'Upper case': to_upper_case,
                                           'Caesar cipher': caesar_cipher})

if TEST_INSTANCE:
    general_par = GeneralPar()
else:
    general_par = GeneralPar

# Shape parameters
expert_p = general_par.param['show_expert']


class PosPar(GParameterized):

    label = 'Position'
    doc = 'Shape position parameters'

    shape = GObjectSelector('star',
                            ['circle', 'polygon', 'star'],
                            style='button',
                            doc="select drawing's shape",
                            allow_None=True)
    n_edge = GInteger(31,
                      bounds=[3, 1000], style='slider', step=2,
                      label="Number of edges",
                      visible=('shape', ['polygon', 'star']),
                      doc="select number of edges of the polygon or star")
    sharpness = GNumber(.65,
                        bounds=[0, 1], style='slider',
                        visible=('shape', 'star'),
                        doc="choose how far edge connections should go")

    x = GNumber(0., bounds=[-1, 1], style='slider',
                doc="horizontal cooordinate of the shape center",
                visible=expert_p)
    y = GNumber(0., bounds=[-1, 1], style='slider',
                doc="vertical cooordinate of the shape center",
                visible=expert_p)
    zoom = GNumber(150., bounds=[10, 1e4], style='slider')


class EdgePar(GParameterized):
    color = GColor('#000000', allow_None=True)
    width = GNumber(1., bounds=[0, 20], style='slider', mode='left',
                    visible='color')
    join_style = GObjectSelector(QtGui.QPen().joinStyle(),
                                 objects={'bevel': Qt.BevelJoin,
                                          'miter': Qt.MiterJoin,
                                          'round': Qt.RoundJoin},
                                 visible=['color', expert_p])
    miter_limit = GNumber(math.inf,  # bounds=[0, None],
                          style='edit',
                          visible=['color', ('join_style', Qt.MiterJoin)])


class FillPar(GParameterized):
    start_folded=True

    color = GColor('#008080', allow_None=True)
    fill_rule = GObjectSelector(Qt.OddEvenFill,
                                objects={'full': Qt.WindingFill,
                                         'odd-even': Qt.OddEvenFill},
                                visible=['color', expert_p])


class ShapePar(GParameterized):
    antialiasing = GBoolean(True, visible=expert_p)

    if not TEST_INSTANCE:
        pos = PosPar
        edge = EdgePar
        fill = FillPar

    def __init__(self):
        super(ShapePar, self).__init__()
        self.pos = PosPar()
        self.edge = EdgePar()
        self.fill = FillPar()


class AllPar(GParameterized):
    if not TEST_INSTANCE:
        general = GeneralPar
        shape = ShapePar

    def __init__(self):
        super(AllPar, self).__init__()
        self.general = general_par
        self.shape = ShapePar()


if TEST_INSTANCE:
    all_par = AllPar()
else:
    all_par = AllPar
shape_par = all_par.shape


# translation: call set_translation when translation parameter is changed
general_par.param.watch(lambda event: set_translation(event.new),
                       'translation')


# This function will test the modification of some parameter attributes
# (does not work perfectly yet?)
def test_watcher():
    # n_edge bounds
    p = shape_par.pos.param.n_edge
    p.bounds = ([3, 8]
                if p.bounds == [3, 1000]
                else [3, 1000])
    # shape options
    p = shape_par.pos.param.shape
    p.objects = (['circle', 'polygon']
                 if p.objects == ['circle', 'polygon', 'star']
                 else ['circle', 'polygon', 'star'])
    # joint style options
    p = shape_par.edge.param.join_style
    objects_dict = {'bevel': Qt.BevelJoin,
                    'miter': Qt.MiterJoin,
                    'round': Qt.RoundJoin}
    names = list(objects_dict.keys())
    objects = list(objects_dict.values())
    if p.objects == objects:
        p.names = names[1:]
        p.objects = objects[1:]
    else:
        p.names = names
        p.objects = objects


# This function resets all parameters to their default values
def reset_parameters():
    par_list = list_all_parameters(all_par, out='Parameterized')
    for obj, names in par_list:  # type: GParameterized, List[str]
        # with pm.batch_watch(obj, run=True):
        for name in names:
            setattr(obj, name, obj.param[name].default)


# When no shape is selected, all controls (except shape itself) are
# disabled
@pm.depends(shape_par.pos.param.shape, watch=True)
def check_shape(_=None):
    # enable/disable all parameters
    pos_par = shape_par.pos
    do_shape = pos_par.shape is not None
    for param in list_all_parameters(shape_par, 'Parameter'):
        if param.name == 'shape':
            continue
        param.enabled = do_shape


check_shape()


# Some drawing controlled by the parameters
class ShapeWidget(QtWidgets.QWidget):

    def __init__(self):
        super(ShapeWidget, self).__init__()

        # redraw on any parameter change
        params = list_all_parameters(shape_par, out='Parameters')
        for param, names in params:
            param.watch(self.redraw, names)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(400, 400)

    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:

        # no drawing
        pos_par = shape_par.pos
        if pos_par.shape is None:
            return

        qp = QtGui.QPainter()
        qp.begin(self)

        if shape_par.antialiasing:
            qp.setRenderHint(QtGui.QPainter.Antialiasing)

        edge_par = shape_par.edge
        pen = qp.pen()
        if edge_par.color is None:
            pen.setStyle(Qt.NoPen)
        else:
            pen.setColor(q_color_from_hex(edge_par.color))
            pen.setWidthF(edge_par.width)
            pen.setJoinStyle(edge_par.join_style)
            pen.setMiterLimit(edge_par.miter_limit)
        qp.setPen(pen)

        fill_par = shape_par.fill
        if fill_par.color is not None:
            qp.setBrush(q_color_from_hex(fill_par.color))

        x = self.width() / 2 + pos_par.x * pos_par.zoom
        y = self.height() / 2 + pos_par.y * pos_par.zoom
        if pos_par.shape == 'circle':
            qp.drawEllipse(QtCore.QPoint(x, y),
                           pos_par.zoom, pos_par.zoom)
        else:
            if pos_par.shape == 'polygon':
                n_draw = 1
                step = 1
            elif pos_par.shape == 'star':
                m = 1
                M = (pos_par.n_edge - 1) // 2
                step = int(np.round(m + (M - m) * pos_par.sharpness))
                # it might be necessary to draw several polygons because a
                # single polygon does not pass through all the edges
                n_draw = math.gcd(step, pos_par.n_edge)
            else:
                raise ValueError('invalid pos_par')
            for k in range(n_draw):
                steps = k + step * np.arange(pos_par.n_edge // n_draw + 1)
                theta = (2 * np.pi / pos_par.n_edge * steps)
                points = np.column_stack((
                    x + np.sin(theta) * pos_par.zoom,
                    y - np.cos(theta) * pos_par.zoom))
                points = [QtCore.QPointF(*point) for point in points]
                polygon = QtGui.QPolygonF(points)
                qp.drawPolygon(polygon,
                               fillRule=fill_par.fill_rule)

        qp.end()

    def redraw(self, *args, **kwargs):
        self.repaint()


# Example Main Window program
class ShapeWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super(ShapeWindow, self).__init__()

        # Central widget
        self.setCentralWidget(QtWidgets.QSplitter())

        # Panel to control parameters
        self.control_widget = TabWidget()
        self.centralWidget().addWidget(self.control_widget)
        tab = ControlPanel(general_par)
        self.control_widget.addTab(tab, 'General')
        tab = ControlPanel(shape_par)
        self.control_widget.addTab(tab, 'Shape')
        self.control_widget.setCurrentIndex(1)

        # Menus
        # (menus generated automatically from general)
        self.menus = ControlMenu(self, 'General', general_par)
        # (additional menus call custom functions)
        self.menus.add_section('Actions')
        self.menus.add_action('Change some attributes', test_watcher,
                              tooltip='This will change n_edge bounds '
                                      'and shape and join_style objects lists')
        self.menus.add_action('Reset all parameters to default values',
                              reset_parameters)
        # # (try a second automatic menu controlling shape parameters!)
        self.second_menus = ControlMenu(self, 'Shape', shape_par)

        # Shape panel
        self.paint = ShapeWidget()
        self.centralWidget().addWidget(self.paint)


# Display main window
app = QtWidgets.QApplication([])
window = ShapeWindow()
# window.control_widget.add_action('Change some attributes', test_watcher,
#                                 tooltip='This will change n_edge bounds '
#                                         'and shape and join_style '
#                                         'objects lists')
window.show()

app.exec()
