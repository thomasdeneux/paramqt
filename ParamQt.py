# requested in param:
# - new slot 'visible' (was added below manually for each class but this is
#   not very nice)
# - public method for '_batch_call_watchers'

import time
import inspect
import traceback
import math
import re
import numpy as np
from typing import List, Callable, Union
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt
from FlowLayout import FlowLayout
import param as pm


# TOOLS


def _error_message(*args):
    """Error message display"""
    msg = '\n'.join([x if isinstance(x, str) else repr(x) for x in args])
    QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical, 'Error', msg).exec()


class InvalidCaseError(Exception):
    """InvalidCaseError should not occur and would be caused by a program bug"""
    pass


def _get_param_base_class(param: pm.Parameter):
    param_base_cls = None
    for cls in inspect.getmro(type(param)):
        if not issubclass(cls, _GraphicParameter):
            param_base_cls = cls
            break
    return param_base_cls


def list_all_parameters(x: Union[pm.Parameterized,
                                 pm.parameterized.ParameterizedMetaclass],
                        out='Parameter'):
    """List recursively the parameter instances, including nested ones,
    of a Parameterized class instance.
    - If out flag is 'Parameters', returns a list of (Params instance, list of
      parameter names) tupples
    - If out flag is 'Parameterized', returns a list of (Parameterized
      instance, list of parameter names) tupples
    - If out flag is 'Parameter', returns a list of Param instances."""

    assert out in ['Parameter', 'Parameters', 'Parameterized']
    names = []
    params = []

    # Current-level parameters
    for name in x.param:
        if name == 'name':
            # not interested in 'name' parameter
            continue
        if out == 'Parameter':
            params.append(x.param[name])
        else:
            names.append(name)

    # Nested Parameterized objects
    for name, value in x.__dict__.items():
        if (isinstance(value, pm.parameterized.ParameterizedMetaclass)
                or isinstance(value, GParameterized)):
            params += list_all_parameters(value, out)

    if out == 'Parameters':
        params.append((x.param, names))
    elif out == 'Parameterized':
        params.append((x, names))
    return params


_QtColors = {QtGui.QColor(color_name).name(): color_name
             for color_name in QtGui.QColor.colorNames()
             if color_name != 'transparent'}


def q_color_from_hex(str):
    if str[0] == '#':
        str = str[1:]
    rgb = int(str, 16)
    return QtGui.QColor.fromRgb(rgb)


def text_display(value, param: pm.Parameter):
    '''Format value to text'''

    if isinstance(param, pm.Integer):
        return str(value)
    elif isinstance(param, pm.Number):
        # display a reasonable number of decimals
        a = math.fabs(value)
        if isinstance(value, int):
            fmt = '{}'
        elif a % 1 == 0:
            # integer
            if value < 1e7:
                fmt = '{:.0f}.'
            else:
                fmt = '{:.3g}'
        else:
            # float
            if a < 1:
                fmt = '{:.3g}'
            elif a < 1e3:
                fmt = '{:.4g}'
            elif a < 1e4:
                fmt = '{:.4g}.'
            else:
                fmt = '{:.3g}'
        return fmt.format(value)
    elif isinstance(param, pm.Color):
        if value is None:
            return '(' + translate('none') + ')'
        if value[0] != '#':
            value = '#' + value
        q_color_name = translate(_QtColors.get(value, None))
        if q_color_name:
            return "%s (%s)" % (q_color_name, value)
        else:
            return value
    else:
        return str(value)


def example_valid_value(param: pm.Parameter):
    '''Return an example non-None parameter value, even if default is None'''
    if param.default is not None:
        return param.default
    if isinstance(param, pm.Boolean):
        return False
    elif isinstance(param, pm.Number):
        try:
            param._validate(0)
            return 0
        except ValueError:
            return param.bounds[0]
    elif isinstance(param, pm.String):
        try:
            param._validate('')
            return ''
        except ValueError:
            raise Exception('Cannot create a valid string parameter value')
    elif isinstance(param, pm.Color):
        return '#000000'
    elif isinstance(param, pm.ObjectSelector):
        try:
            return param.objects[0]
        except IndexError:
            raise Exception('Cannot create a valid value for selector '
                            'parameter with empty list of objects')
    else:
        raise Exception('Case not handled yet: example value for parameter '
                        'of type %s' % type(param))


# PARAM WRAPPING

GRAPHIC_BUTTON_SIZE = QtCore.QSize(64, 64)


class _GraphicParameter(pm.Parameter):
    """A subclass Parameters with additional attributes, which for the
    moment will all be stored in the available 'precedence' slot."""

    def __init__(self, *args, style=None, **kwargs):
        user = kwargs.pop('precedence', dict())

        # new attribute 'style' (default None)
        user['style'] = style

        # any additional attribute can be created (all arguments other than
        # slots and 'label')
        slots = [key
                 for cls in inspect.getmro(type(self)) if
                 issubclass(cls, pm.Parameter)
                 for key in cls.__slots__]
        slots.append('label')
        user_keys = [key for key in kwargs.keys() if key not in slots]
        for key in user_keys:
            user[key] = kwargs.pop(key)

        super(_GraphicParameter, self).__init__(*args, instantiate=True,
                                                **kwargs)

        self.user = user

        # 'visible' and 'enabled' can be set to a boolean value or to a
        # list of dependencies!
        user['_dependencies'] = {'visible': [], 'enabled': []}

        if not isinstance(self.visible, bool):
            self.add_dependencies('visible', self.visible)

        if not isinstance(self.enabled, bool):
            self.add_dependencies('enabled', self.enabled)

    @property
    def user(self):
        return self.precedence

    @user.setter
    def user(self, value):
        self.precedence = value

    def add_dependencies(self, flag: str, dep_list: list):
        # flag must be 'visible' or 'enabled'
        # dep_list is a list of any of:
        # - parameter instance (will be converted to bool)
        # - (parameter instance, list of accepted values)

        dependencies = self.user['_dependencies'][flag]

        if not isinstance(dep_list, list):
            dep_list = [dep_list]
        dependencies += dep_list

        # # set watchers
        # def check_dependencies_flag(*args):
        #     self.check_dependencies(flag)
        #
        # for dep in dep_list:
        #     if isinstance(dep, tuple):
        #         param, _ = dep
        #     else:
        #         param = dep  # type: pm.Parameter
        #     pm.depends(param, watch=True)(check_dependencies_flag)

        if self.owner is not None:
            self.check_dependencies(flag)

    def check_dependencies(self, flag=None):

        # check both visible and enabled?
        if flag is None:
            self.check_dependencies('visible')
            self.check_dependencies('enabled')
            return

        dependencies = self.user['_dependencies'].get(flag, [])

        ok = True
        for dep in dependencies:
            # dependency specification
            if isinstance(dep, tuple):
                param, accepted_values = dep
                if not isinstance(accepted_values, list):
                    accepted_values = [accepted_values]
            else:
                param = dep  # type: Union[pm.Parameter, str]
                accepted_values = None

            # dependent parameter's value
            if isinstance(param, pm.Parameter):
                obj = param.owner
                name = param.name
            elif isinstance(param, str):
                obj = self.owner
                name = param
            else:
                ValueError('dependency must be either a parameter instance '
                           'or a string referencing a parameter')
            value = getattr(obj, name)

            # acceptance
            if accepted_values is None:
                ok = bool(value)
            else:
                # evaluate value as bool
                ok = value in accepted_values
            # print(name, ':', value, '->', ok)
            if not ok:
                break

        if flag == 'visible':
            self.visible = ok
        elif flag == 'enabled':
            self.enabled = ok
        else:
            ValueError("Dependency flag can only be 'visible' or 'enabled'")

    def check_dependencies_visible(self, _=None):
        self.check_dependencies('visible')

    def check_dependencies_enabled(self, _=None):
        self.check_dependencies('enabled')

    def __setattr__(self, key, value):
        super(_GraphicParameter, self).__setattr__(key, value)

        # set dependencies watching only once the owner is set
        if key == 'owner' and value is not None:
            for flag, callback in [('visible', self.check_dependencies_visible),
                                   ('enabled', self.check_dependencies_enabled)]:
                dep_list = self.user['_dependencies'][flag]
                if not dep_list:
                    continue

                for dep in dep_list:
                    if isinstance(dep, tuple):
                        dep_param, _ = dep
                    else:
                        dep_param = dep  # type: pm.Parameter

                    if isinstance(dep_param, pm.Parameter):
                        dep_param.owner.param.watch(callback, dep_param.name)
                    elif isinstance(dep_param, str):
                        self.owner.param.watch(callback, dep_param)
                    # execute callback once to possibly fix visibility
                    callback()


class GBoolean(_GraphicParameter, pm.Boolean):
    # We need a new slot 'visible' so that this new attribute can be watched
    # using pm.Parameterized.watch
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GBoolean, self).__init__(*args, **kwargs)


class GInteger(_GraphicParameter, pm.Integer):
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GInteger, self).__init__(*args, **kwargs)


class GNumber(_GraphicParameter, pm.Number):
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GNumber, self).__init__(*args, **kwargs)


class GString(_GraphicParameter, pm.String):
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GString, self).__init__(*args, **kwargs)


class GObjectSelector(_GraphicParameter, pm.ObjectSelector):
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GObjectSelector, self).__init__(*args, **kwargs)


class GListSelector(_GraphicParameter, pm.ListSelector):
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GListSelector, self).__init__(*args, **kwargs)


class GList(_GraphicParameter, pm.List):
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GList, self).__init__(*args, **kwargs)


class GColor(_GraphicParameter, pm.Color):
    __slots__ = ['visible', 'enabled']

    def __init__(self, *args, visible=True, enabled=True, **kwargs):
        self.visible, self.enabled = visible, enabled
        super(GColor, self).__init__(*args, **kwargs)
        # handle current bug in pm.Color (allow_None argument is ignored)
        if 'allow_None' in kwargs:
            self.allow_None = kwargs['allow_None']


# sub-class pm.Parameterized to update the visible and enabled attributes
# of the object parameters at the end of object's initialization
class GParameterized(pm.Parameterized):

    label = ''
    doc = ''
    start_folded = False

    def __init__(self, *args, **kwargs):
        super(GParameterized, self).__init__(*args, **kwargs)

        for param in self.param.params().values():
            if isinstance(param, _GraphicParameter):
                param.check_dependencies()


# HANDLING TRANSLATION AND TRANSLATION CHANGES


# Translation functions: user registers a translation function using
# set_translation, which will be used by the program to translate strings
class _InternalPar(pm.Parameterized):

    translation = pm.Parameter(default=None)
    # If a tooltip translation is set, use it to translate tooltips based on
    # parameter names
    tooltip_translation = pm.Parameter(default=None)


def set_translation(translation: Callable[[str], str],
                    tooltip_translation: Callable[[str], str]=None):
    if tooltip_translation is not None:
        _InternalPar.tooltip_translation = tooltip_translation
    _InternalPar.translation = None  # hack to make sure an update will occur, TODO: remove this
    _InternalPar.translation = translation


def translate(s: str) -> str:
    if s is None:
        return None
    s = str(s)
    tr = _InternalPar.translation
    if tr is None:
        return s
    else:
        return tr(s)


def translate_tooltip(s: str) -> str:
    if s is None:
        return None
    s = str(s)
    tr = _InternalPar.tooltip_translation
    if tr is None:
        tip = None
    else:
        tip = tr(s)
        if tip == s or tip == 'x':
            tip = None
    return tip


class TranslationProne:
    """Classes inheriting from _TranslationProne will have their
    _update_text method automatically called when the translation function
    is changed"""

    def __init__(self, *args, **kwargs):
        super(TranslationProne, self).__init__(*args, **kwargs)
        _InternalPar.param.watch(lambda _: self._update_text(),
                                 'translation')
        try:
            self._update_text()
        except AttributeError:
            # Initialization of object might not be fully terminated,
            # hence some attributes not defined yet
            pass


    def _update_text(self):
        '''Must be overwritten in sub-classes'''
        pass


class Label(TranslationProne, QtWidgets.QLabel):

    def __init__(self, label, *args, **kwargs):
        self._label = label
        super(Label, self).__init__(label, *args, **kwargs)

    def _update_text(self):
        self.setText(translate(self._label))


class TabWidget(TranslationProne, QtWidgets.QTabWidget):

    def __init__(self, *args, **kwargs):
        super(TabWidget, self).__init__(*args, **kwargs)
        self._tab_text = []

    def addTab(self, widget: QtWidgets.QWidget, title: str) -> int:
        self._tab_text.append(title)
        return super(TabWidget, self).addTab(widget, translate(title))

    def insertTab(self, index: int, widget: QtWidgets.QWidget, title: str) -> int:
        self._tab_text.insert(index, title)
        return super(TabWidget, self).insertTab(index, widget, translate(title))

    def _update_text(self):
        for i, title in enumerate(self._tab_text):
            self.setTabText(i, translate(title))


# HANDLING ERRORS WHEN EXECUTING A CALLBACK

def _return_false(err: Exception):
    """An error handler that does not handle any error"""
    return False


_set_error_handler = _return_false
_reset_error_handler = _return_false


def set_error_handler(set_error_handler: Callable[[Exception], bool],
                      reset_error_handler: Callable[[Exception], bool] = None):
    global _set_error_handler
    global _reset_error_handler
    _set_error_handler = set_error_handler
    if reset_error_handler is not None:
        _reset_error_handler = reset_error_handler


# ABSTRACT CLASSES FOR CONTROL OF ONE PARAMETER

class _ParameterControlBase(TranslationProne):
    """
    Abstract class for controlling parameters graphically. Sub-class will
    implement the actual graphics, either through controls or through menu items
    """

    def __init__(self, obj: pm.Parameterized, name: str,
                 do_label: bool = False,
                 **kwargs):

        super(_ParameterControlBase, self).__init__(**kwargs)

        # Object, key, value, specifications
        self.obj = obj
        self.name = name
        self.param = obj.param[name]  # type: pm.Parameter
        self._param_base_cls = _get_param_base_class(self.param)

        # Watch parameter changes
        if not self.param.constant:
            obj.param.watch(self.update_display, name)
            obj.param.watch(self.update_display, name, what='enabled')
            obj.param.watch(self.update_display, name, what='visible')

        # Create label: stored as an attribute (note that this must occur
        # after _init_control, i.e. after super-class __init__() of the
        # accurate QWidget has been called)
        if do_label:
            if self.param.allow_None:
                self._label_display = QtWidgets.QCheckBox()
                self._label_display.toggled.connect(self._toggle_None)
            else:
                self._label_display = QtWidgets.QLabel()
        else:
            self._label_display = None

        # Init control: will be done in the specialized child class,
        # this will include the call to the QtWidget constructor
        self._init_control()

        # Display text and tooltips
        self._update_text()

        # Init display: update everything
        for what in ['value', 'enabled', 'visible']:
            self.update_display(what, init=True)

    @property
    def t_label(self):
        # Do not use automatic name formatting of param
        return translate(self.param._label or self.name)

    @property
    def t_tooltip(self):
        if self.param.doc is not None:
            return translate(self.param.doc)
        else:
            return translate_tooltip(self.param._label or self.name)

    def parameter_value(self):
        value = getattr(self.obj, self.name)
        if self._param_base_cls == pm.Number:
            # if value must be a float, let it be a float! (avoid integers)
            value = float(value)
        return value

    def set_parameter_value(self, value):
        # This method will handle errors due to invalid value but not due to
        # failing watchers

        # Memorize previous value in case we need to switch back
        prev_value = self.parameter_value()

        # Attempt to set the value, do not run the watchers yet (otherwise
        # we would not know whether a ValueError is caused by an invalid
        # value or by a watcher failing)
        try:
            with pm.batch_watch(self.obj, run=False):
                setattr(self.obj, self.name, value)
        except ValueError as err:
            # invalid value, parameter was not changed
            print(repr(err))
            traceback.print_tb(err.__traceback__)
            _error_message(
                translate("Cannot set parameter '%s':" % self.name),
                str(err)
            )
            # restore display for the original value
            self._update_value_display()
            return

        # Call the watchers, handle errors
        try:
            self.obj.param._batch_call_watchers()
        except Exception as err:
            # error will be considered handled if returned value is True
            # or None (no returned value)
            error_handled = (_set_error_handler(err) != False)
            if not error_handled:
                print(repr(err))
                traceback.print_tb(err.__traceback__)
                try:
                    setattr(self.obj, self.name, prev_value)
                    _error_message(
                        translate("Setting parameter '%s' failed with "
                                       "error:") % self.name,
                        err,
                        translate("Previous value was restored.")
                    )
                except Exception as err2:
                    error_handled = (_reset_error_handler(err2) != False)
                    if not error_handled:
                        print(repr(err2))
                        traceback.print_tb(err2.__traceback__)
                        _error_message(
                            translate(
                                "Setting parameter '%s' failed with "
                                "error:") % self.name,
                            err,
                            translate(
                                "Restoring previous value also failed "
                                "with error:"),
                            err2
                        )

    def _init_control(self):
        pass

    def update_display(self, what, init=False):

        if isinstance(what, pm.parameterized.Event):
            event = what
            what = event.what
        if what == 'value':
            # at init, if value is None and there is a checkbox label, put the
            # default value in the control widget
            if init and self._label_display and self.parameter_value() is None:
                self._display_value(example_valid_value(self.param))
            self._update_value_display()
        elif what == 'enabled':
            self.set_enabled(self.param.enabled)
        elif what == 'visible':
            visible = getattr(self.param, 'visible', True)
            if not (init and visible):
                # at init do not explicitly make the control visible as this
                # would show it alone, i.e. not inside its parent container;
                # but if it should not be visible, set its visibility to
                # False and it will not be shown when the container will be
                # shown
                self.set_visible(visible)
        else:
            print("event of type '%s' not handled yet" % what)

    def _update_value_display(self, _=None):
        value = self.parameter_value()
        if self.param.allow_None and self._label_display:
            self._label_display.setChecked(value is not None)
            if value is None:
                return
        self._display_value(value)

    def _display_value(self, value):
        raise NotImplementedError

    def _update_text(self):
        # reimplemented in some child classes

        if self._label_display:
            self._label_display.setText(self.t_label)
            self._label_display.setToolTip(self.t_tooltip)
        else:
            self.setToolTip(self.t_tooltip)

    def _control_has_None(self):
        return bool(self.param.allow_None) and not self._label_display

    def _toggle_None(self):
        if self._label_display.isChecked():
            if self.parameter_value() is None:
                self._set_parameter_from_control()
            self.setEnabled(True)
        else:
            if self.parameter_value() is not None:
                self.set_parameter_value(None)
            self.setEnabled(False)

    def _set_parameter_from_control(self, _=None):
        self.set_parameter_value(self._value_from_control())

    def _value_from_control(self):
        raise NotImplementedError

    def set_enabled(self, value):
        if self._label_display:
            self._label_display.setEnabled(value)
            self.setEnabled(value and not (self.parameter_value() is None))
        else:
            self.setEnabled(value)

    def set_visible(self, value):
        if self._label_display:
            self._label_display.setVisible(value)
        self.setVisible(value)

    def mouseDoubleClickEvent(self, _=None):
        # reset value to default
        self.set_parameter_value(self.param.default)


class _ColorControlBase(_ParameterControlBase):

    def _choose_color(self, _=None):
        if self.parameter_value() is None:
            dialog = QtWidgets.QColorDialog()
        else:
            q_color = q_color_from_hex(self.parameter_value())
            dialog = QtWidgets.QColorDialog(q_color)

        def finished(_=None):
            q_color = dialog.selectedColor()
            self.set_parameter_value(q_color.name())

        dialog.finished.connect(finished)

        def set_default(_=None):
            dialog.close()
            self.set_parameter_value(self.param.default)

        dialog.mouseDoubleClickEvent = set_default
        dialog.exec()


class _SelectorControlBase(_ParameterControlBase):

    def _init_control(self):
        # Add watcher on objects
        self.obj.param.watch(self._update_objects_list, self.name,
                             what='names')
        self.obj.param.watch(self._update_value_display, self.name,
                             what='objects')

    def _update_objects_list(self, _=None):
        # will be reimplemented in child classes, unless in fact there is
        # nothing to do (as is the case with CyclingButton)
        pass

    def _populate_object_name_dict(self):
        # populate the objects to names and tooltips dictionary
        names = self.param.names
        if names is not None:
            self._objects_to_names = {names[key]:key for key in names.keys()}
        else:
            self._objects_to_names = {value:str(value) for value in self.param.objects}

    def _populate_object_tooltip_dict(self):
        tooltips = self.param.precedence.get('value_tooltips', None)
        if tooltips is not None:
            self._objects_to_tooltips = dict(zip(self.param.objects, tooltips))
        else:
            self._objects_to_tooltips = None

    def all_values(self):
        if self._control_has_None():
            return [None] + self.param.objects
        else:
            return self.param.objects

    def all_value_names(self):
        names = self.param.names
        if names is None:
            names = [str(obj) for obj in self.param.objects]
        else:
            names = [key for key in self.param.names.keys()]
        if self._control_has_None():
            return ['-'] + names
        else:
            return names

    def value_name(self, value):
        try:
            if value is None:
                return '-'
            else:
                return self._objects_to_names[value]
        except AttributeError:
            self._populate_object_name_dict()
            return self.value_name(value)

    def all_value_tooltips(self):
        tooltips = self.param.precedence.get('value_tooltips', None)
        if tooltips is None:
            return [None] * (
                    self._control_has_None() + len(self.param.objects))
        elif self._control_has_None():
            return [None] + tooltips
        else:
            return tooltips

    def value_tooltip(self, value):
        try:
            if value is None or self._objects_to_tooltips is None:
                return None
            else:
                return self._objects_to_tooltips[value]
        except AttributeError:
            self._populate_object_tooltip_dict()
            return self.value_tooltip(value)


# SPECIALIZED PANEL CONTROLS


class ConstantDisplay(_ParameterControlBase, QtWidgets.QLabel):

    def _init_control(self):
        # Simple text display
        self.setText(str(self.parameter_value()))
        # prevent label form extending vertically
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                           QtWidgets.QSizePolicy.Maximum)

    def _display_value(self, value):
        self.setText(str(self.parameter_value()))


class PopupMenu(_SelectorControlBase, QtWidgets.QComboBox):

    def _init_control(self):
        # (allow control shrinking!)
        self.minimumSizeHint = lambda: QtCore.QSize(0, 0)
        self._make_combo_items()
        self.activated.connect(self._set_parameter_from_control)

    def _make_combo_items(self):
        '''Fill-in the options for popup list of values'''
        value_names = self.all_value_names()
        self.clear()
        self.insertItems(0, [translate(x) for x in value_names])
        if isinstance(self.param,
                      GObjectSelector) and self.all_value_tooltips():
            for i, tooltip in enumerate(self.all_value_tooltips()):
                if tooltip is None:
                    tooltip = translate_tooltip(value_names[i])
                self.setItemData(i, translate(tooltip), Qt.ToolTipRole)

    def _update_objects_list(self, _=None):
        super(PopupMenu, self)._update_objects_list(_)
        self._make_combo_items()
        self._update_value_display()

    def _value_from_control(self):
        return self.all_values()[self.currentIndex()]

    def _update_text(self):
        super(PopupMenu, self)._update_text()
        self._make_combo_items()
        self._update_value_display()

    def _display_value(self, value):
        values = self.all_values()
        try:
            self.setCurrentIndex(values.index(value))
        except ValueError:
            # Can happen when list of objects has changed but
            # param.ObjectSelector did not verify again the value
            self.set_parameter_value(values[0])


class CyclingButton(_SelectorControlBase, QtWidgets.QPushButton):

    def _init_control(self):
        # if None is allowed: make button checkable, and special
        # timed mechanism to switch between different options when
        # clicking the button fast enough, but switch back to OFF
        # when clicking after a delay
        if self._control_has_None():
            self.setCheckable(True)
            self.toggled.connect(self._value_edited)
        else:
            self.clicked.connect(self._value_edited)
        self._last_click_time = 0

    def _update_text(self):
        super(CyclingButton, self)._update_text()
        self._update_value_display()

    def _value_from_control(self):
        # easier is to try every value until the button text matches
        button_txt = self.text()
        for value in self.param.objects:
            if self._button_text(value) == button_txt:
                return value

        # if this fails (button displays a non-expected text, should not
        # happen), return the first value among possible values rather than
        # raise an exception
        return self.param.objects[0]

    def _value_edited(self, _=None):
        prev_value = getattr(self.obj, self.name)
        try:
            prev_value_idx = self.all_values().index(prev_value)
        except ValueError:
            # can happen because list of objects was changed but
            # param.ObjectSelector did not verify at that time that value
            # was still valid
            prev_value_idx = -1
        if (self._control_has_None() and prev_value is not None
                and (time.time() - self._last_click_time) > 2):
            # go directly back to None
            value = None
        else:
            # cycle through values
            value_idx = (prev_value_idx + 1) % len(self.all_values())
            value = self.all_values()[value_idx]
        self._last_click_time = time.time()

        self.set_parameter_value(value)

    def _display_value(self, value):
        self.setChecked(value is not None)
        button_txt = self._button_text(value)
        self.setText(button_txt)
        # set checked state after a tiny delay, to make sure this
        # happens after the automatic toggling of the toggle button
        QtCore.QTimer.singleShot(
            100, lambda: self.setChecked(bool(value)))

    def _button_text(self, value):
        value_txt = translate(value) if value is not None else '-'
        if not self._label_display:
            # add label on the button text if there is no label widget
            value_txt = (
                    self.t_label
                    + translate(': ') + value_txt
            )
        return value_txt


def icon_path(name):
    # type: (str) -> str
    return "images/icons/%s.png" % name


def create_on_off_icons(name):
    icon_name = icon_path(name)
    on_pixmap = QtGui.QPixmap(icon_name)

    # Create a semitransparent pixmap for the disabled one
    off_pixmap = QtGui.QPixmap(on_pixmap.size())
    off_pixmap.fill(Qt.transparent)

    painter = QtGui.QPainter(off_pixmap)
    painter.setOpacity(0.35)
    painter.drawPixmap(0, 0, on_pixmap)
    painter.end()

    return QtGui.QIcon(on_pixmap), QtGui.QIcon(off_pixmap)


class ButtonGroup(_SelectorControlBase, QtWidgets.QWidget):
    def _init_control(self):
        # Set if the button group accepts multiple elements
        self._multi = self.param.user.get('multivalues', False)

        # True if the button group allows empty lists
        self._allow_empty = self.param.user.get('allow_empty', True)

        # Whether the button is graphic or not
        self._graphic = self.param.user.get('graphic', False)

        self._update_buttons()

        # A sensible default (_current_idx is not applicable for multivalue ButtonGroups)
        if not self._multi:
            if self._control_has_None():
                self._current_idx = None
            else:
                self._current_idx = 0
                self._check_button(0, True)

    def _update_buttons(self):
        # this is a container widget, and as such, it needs to be populated
        layout = FlowLayout()
        self._buttons = []   # type: [QtWidgets.QPushButton]

        # Generate two sets of icons
        if self._graphic:
            self._on_icons = []  # type: [QtGui.QIcon]
            self._off_icons = []  # type: [str:QtGui.QIcon]

        # add a button for each of the objects of the parameter
        for i, value in enumerate(self.param.objects):
            button = QtWidgets.QPushButton() # type: QtWidgets.QPushButton
            button.setCheckable(True)

            if self._graphic:
                vs = str(value)
                icon_name = self.name + '/' + vs
                on_icon, off_icon = create_on_off_icons(icon_name)
                button.setIcon(off_icon)
                button.setIconSize(GRAPHIC_BUTTON_SIZE)

                self._on_icons.append(on_icon)
                self._off_icons.append(off_icon)

            # the toggled action - this is necessary because Python captures the
            # variables by reference, not by value
            def make_signal(i, value):
                return lambda: self._button_toggled(i, value)

            button.clicked.connect(make_signal(i, value))
            layout.addWidget(button)
            self._buttons.append(button)

        # Update the button's texts
        self._update_button_texts()

        # Update the control's layout
        self.setLayout(layout)

    def _update_button_texts(self):
        for button, value in zip(self._buttons, self.param.objects):
            name = self.value_name(value)
            tooltip = self.value_tooltip(value)

            t_name = '-' if name is None else translate(name)
            t_tooltip = (translate(tooltip) if tooltip is not None
                         else translate_tooltip(name))

            # Turn it into a graphic button if it is set
            if self._graphic:
                if t_tooltip is None:
                    button.setToolTip(t_name)
                else:
                    button.setToolTip(t_name + '\n' + t_tooltip)
            else:
                button.setText(t_name)
                button.setToolTip(t_tooltip)

    def _update_text(self):
        super(ButtonGroup, self)._update_text()
        self._update_button_texts()
        self._update_value_display()

    def _update_objects_list(self, _=None):
        super(ButtonGroup, self)._update_objects_list(_)
        self._update_buttons()
        self._update_value_display()

    def _button_toggled(self, i, value):
        # type: (int, str) -> void

        # special handling require only for non-multivalue ButtonGroups
        if not self._multi:
            # if there was no value before, just go away
            if self._current_idx is None:
                pass
            elif self._current_idx == i:
                # if the index is the same, it depends on whether the control
                # allows None or not
                if self._control_has_None():
                    i = None
                    value = None
                else:  # recheck the button
                    self._check_button(i, True)
            else:  # uncheck the last button
                self._check_button(self._current_idx, False)

            # now, set the value
            self._current_idx = i
            self.set_parameter_value(value)
        else:
            # just return whatever it is from _value_from_control
            values = self._value_from_control()

            # take care of not allowing empty values if requested
            if not self._allow_empty and len(values) == 0:
                self._check_button(i, True)
                values.append(value)

            self.set_parameter_value(values)

    def _value_from_control(self):
        if not self._multi:
            if self._current_idx is None and self._control_has_None():
                return None
            else:
                try:
                    return self.param.objects[self._current_idx]
                except IndexError:
                    return self.param.objects[0]
        else:
            # Use a list comprehension to filter all the values
            return [val
                    for i, val in enumerate(self.param.objects)
                    if self._buttons[i].isChecked()]

    def _display_value(self, value):
        if not self._multi:
            # update the index if necessary
            try:
                idx = self.param.objects.index(value)
            except ValueError:
                idx = None if self._control_has_None() else 0

            if self._current_idx is not None:
                self._check_button(self._current_idx, False)

            if idx is not None:
                self._check_button(idx, True)

            self._current_idx = idx
        else:   # just set them as checked
            if value is not None:
                values = set(value)
                for i, name in enumerate(self.param.objects):
                    self._check_button(i, name in values)

    def _check_button(self, i, checked):
        self._buttons[i].setChecked(checked)
        self._buttons[i].setIcon(self._on_icons[i] if checked else self._off_icons[i])


class ButtonMenu(_SelectorControlBase, QtWidgets.QPushButton):
    def _init_control(self):
        super(ButtonMenu, self)._init_control()
        # Create the menu that will be used for it
        self._menu = QtWidgets.QWidget()

        # update the buttons
        self._update_buttons()

        # set the characteristics of the popup menu
        self._menu.setWindowFlags(Qt.Popup)
        self._menu.setWindowModality(Qt.WindowModal)
        self._menu.hide()
        self.clicked.connect(self._show_menu)
        self.setCheckable(self._control_has_None())

    def _update_buttons(self):
        layout = FlowLayout()
        self._buttons = []  # type: [QtWidgets.QPushButton]

        for value in self.all_values():
            # add the button
            button = QtWidgets.QPushButton()
            button.setIcon(QtGui.QIcon(icon_path(self.name + '/' + str(value))))
            button.setIconSize(GRAPHIC_BUTTON_SIZE)
            self._buttons.append(button)
            layout.addWidget(button)

            # again this technique to not "capture" the for variable
            def make_lambda(value):
                return lambda: self._button_selected(value)
            button.clicked.connect(make_lambda(value))

        # Update the button's texts
        self._update_button_texts()
        self._menu.setLayout(layout)

    def _update_button_texts(self):
        for button, value in zip(self._buttons, self.all_values()):
            name = self.value_name(value)
            tooltip = self.value_tooltip(value)

            t_name = '-' if name is None else translate(name)
            t_tooltip = (translate(tooltip) if tooltip is not None
                         else translate_tooltip(name))

            if t_tooltip is None:
                button.setToolTip(t_name)
            else:
                button.setToolTip(t_name + '\n' + t_tooltip)

    def _show_menu(self):
        self._ensure_checked_state()
        self._adjust_menu_size()

        # Check if the menu could be partially invisible
        gpos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        ymax = QtWidgets.QApplication.desktop().screenGeometry().bottom()
        if gpos.y() + self._menu.height() > ymax:
            gpos.setY(gpos.y() - self.height() - self._menu.height())

        # move the popup menu here, since at the _init_control
        # the menu hasn't been positioned
        self._menu.move(gpos)
        self._menu.show()

    def _button_selected(self, value):
        self._menu.hide()
        self.set_parameter_value(value)

    def _adjust_menu_size(self):
        # first, set the width to the maximum size
        width = self.parent().width()
        layout = self._menu.layout()  # type: FlowLayout
        self._menu.setFixedSize(layout.sizeParams(width))

    def _update_objects_list(self, _=None):
        super(ButtonMenu, self)._update_objects_list(_)
        self._update_buttons()
        self._update_value_display()

    def _update_text(self):
        super(ButtonMenu, self)._update_text()
        self._update_button_texts()
        self._update_value_display()

    def _value_from_control(self):
        return self._current_value

    def _display_value(self, value):
        self._current_value = value

        # Set if the value is None
        t_label = self.t_label + translate(': ')
        if value is not None:
            self.setToolTip(t_label + translate(self.value_name(value)))
        else:
            self.setToolTip(t_label + '-')

        self.setIcon(QtGui.QIcon(icon_path(self.name + '/' + str(value))))
        self.setIconSize(GRAPHIC_BUTTON_SIZE)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._ensure_checked_state()

    def _ensure_checked_state(self):
        # Set the checked value
        self.setChecked(self._control_has_None() and self._current_value is not None)


class ToggleButton(_ParameterControlBase, QtWidgets.QPushButton):

    def _init_control(self):
        # whether the button should appear negated
        self._negated = self.param.user.get('negated', False)

        # push button to cycle between values
        self.setCheckable(True)
        self.toggled.connect(self._set_parameter_from_control)

    def _update_text(self):
        super(ToggleButton, self)._update_text()
        self._update_value_display()

    def _value_from_control(self):
        if self._negated:
            return not self.isChecked()
        return self.isChecked()

    def _display_value(self, value):
        if self._negated:
            value = not value

        self.setChecked(value)
        value_txt = translate('ON') if value else translate('OFF')
        if not self._label_display:
            # add label on the button text if there is no label widget
            value_txt = (
                    self.t_label + translate(': ')
                    + value_txt)
        self.setText(value_txt)


class GraphicToggleButton(_ParameterControlBase, QtWidgets.QPushButton):

    def _init_control(self):
        # whether the button should appear negated
        self._negated = self.param.user.get('negated', False)

        # push button to cycle between values
        self.setCheckable(True)
        self.toggled.connect(self._set_parameter_from_control)

        # set the graphic button
        try:
            on_name = icon_path(self.param.user['separate_icons'][0])
            off_name = icon_path(self.param.user['separate_icons'][1])
            self._on_icon = QtGui.QIcon(on_name)
            self._off_icon = QtGui.QIcon(off_name)
        except (KeyError, IndexError):
            if self.param.user.get('fade_off', False):
                self._on_icon, self._off_icon = create_on_off_icons(self.name)
            else:
                self._on_icon = self._off_icon = QtGui.QIcon(icon_path(self.name))

        self._on_label, self._off_label = self.param.user.get('separate_labels', [None, None])
        self._separate_labels = self._on_label is not None

        self.setIconSize(GRAPHIC_BUTTON_SIZE)

    def _update_text(self):
        super(GraphicToggleButton, self)._update_text()
        self._update_value_display()

    def _value_from_control(self):
        if self._negated:
            return not self.isChecked()
        return self.isChecked()

    def _display_value(self, value):
        if self._negated:
            value = not value

        self.setChecked(value)
        self.setIcon(self._on_icon if value else self._off_icon)

        if self._separate_labels:
            self.setToolTip(translate(self._on_label if value else self._off_label))
        else:
            self.setToolTip(self.t_label)


class CheckBox(_ParameterControlBase, QtWidgets.QCheckBox):

    def _init_control(self):
        self.toggled.connect(self._set_parameter_from_control)

    def _value_from_control(self):
        return self.isChecked()

    def _display_value(self, value):
        self.setChecked(value)

    def _update_text(self):
        if self._label_display:
            _ParameterControlBase._update_text(self)
        else:
            self.setText(self.t_label)


class Slider(_ParameterControlBase, QtWidgets.QSlider):
    """Slider offers a fast-interacting control for an integer or float
    parameter. Its control of the parameter can be non linear, for example
    logarithmic (e.g. when value can vary between 1 and 1000, one often needs
    fine-grain control near 1, but only coarse-grain control near 1000):
    this can be adjusted with the `mode` user attribute; available modes are
    - linear    linear control between min and max
    - log       logarithmic control between min (needs to be >0) and max
    - left E    finer grain near min, coarser grain near max, value E
                controls the effect strength (typically interval [0 1],
                uses function x -> x^E)
    - right E   finer grain near max
    - middle E  finer grain near interval center (typically 0 or 1)
    - ext E     finer grain near min and max
    - tan X     use tangente function when one or both sides is infinite,
                value X controls the slope near zero if both sides are
                infinite, or near the finite side otherwise
    If `mode` is not set, it is automatically inferred from the bounds."""

    def _init_control(self):
        # Add watcher on bounds
        self.obj.param.watch(self._update_value_display, self.name,
                             what='bounds')

        # check that bounds are defined
        bounds = self.param.bounds
        if bounds is None or any([b is None for b in bounds]):
            raise ValueError('bounds need to be defined for slider '
                             'control')
        if self._control_has_None():
            raise ValueError('slider control not available when '
                             'allowing None')
        # make (maximum-minimum) divisible by a large number of integers to
        # minimize the chances of rounding errors on float values
        self.setMinimum(0)
        self.setMaximum(6300)  # 6300 = 2^2 * 3^2 * 5^2 * 7
        self.setOrientation(Qt.Horizontal)
        self.valueChanged.connect(self._value_edited)
        self._slider_callback_enabled = True
        self.actionTriggered.connect(self._adjust_slider_step)
        # mechanism to detect double-clicks on the slider handle (see
        # mouseDoubleClickEvent below)
        self._slider_step = None
        self.sliderPressed.connect(lambda: setattr(self, '_slider_step', None))

    def mouseDoubleClickEvent(self, ev):
        # reset value to default when slider handle was double-clicked,
        # otherwise treat double-clicks as normal clicks performing a slider
        # step event
        if self._slider_step is None:
            super(Slider, self).mouseDoubleClickEvent(ev)
        else:
            if self._param_base_cls == pm.Integer:
                self._adjust_slider_step(self._slider_step)
            else:
                QAS = QtWidgets.QAbstractSlider
                if self._slider_step == QAS.SliderPageStepSub:
                    self.setValue(self.value() - self.pageStep())
                elif self._slider_step == QAS.SliderPageStepAdd:
                    self.setValue(self.value() + self.pageStep())

    def _adjust_slider_step(self, ev):
        # memorize event
        self._slider_step = ev
        # When slider is being stepped, step value by one unit if parameter
        # value is integer
        if self._param_base_cls != pm.Integer:
            return
        QAS = QtWidgets.QAbstractSlider
        value = self.parameter_value()
        bounds = self.param.bounds
        step = self.param.step  # 'step' exists as a slot!
        if ev == QAS.SliderPageStepSub:
            value -= step
            if bounds[0]:
                value = max(value, bounds[0])
            self.set_parameter_value(value)
        elif ev == QAS.SliderPageStepAdd:
            value += step
            if bounds[1]:
                value = min(value, bounds[1])
            self.set_parameter_value(value)

    def _slider_conversion(self, x, from_control: bool):
        bounds = self.param.bounds
        b, B = bounds  # type: float
        if b is not None and math.isinf(b):
            b = None
        if B is not None and math.isinf(B):
            B = None

        # determine mode
        mode = self.param.user.get('mode', None)
        if b is None or B is None:
            # at least one bound is infinite
            if mode is not None and 'tan' not in mode:
                raise ValueError("Slider mode must be 'tan' when at least one "
                                 "bound is infinite")
            mode = 'tan'
        elif mode is None:
            if (b == -B) or (b >= 0 and b + B == 2):
                # interval is centered on 0 or on 1, be more fine-grained in
                # the middle
                mode = 'middle'
            elif b > 0 and B >= 50 * b:
                # logarithmic scale
                mode = 'log'
            else:
                mode = 'linear'
        elif mode == 'log' and b <= 0:
            raise ValueError("Slider mode can't be 'log' if lower bound "
                             "isn't positive")
        pattern = '(linear|log|left|right|middle|ext|tan) *(\d*\.?\d*)'
        mode, strength = re.search(pattern, mode).groups()
        strength = float(strength) if strength else 1.

        # initial linear mapping between slider and some interval
        if mode == 'linear':
            map_control = (b, B)
            aff_value = None
        elif mode == 'log':
            map_control = (math.log(b), math.log(B))
            aff_value = None
        elif mode == 'left':
            map_control = (0, 1)
            aff_value = (b, B - b)
        elif mode == 'right':
            map_control = (1, 0)
            aff_value = (B, b - B)
        elif mode in ['middle', 'ext']:
            map_control = (-1, 1)
            aff_value = ((b + B) / 2, (B - b) / 2)
        elif mode == 'tan':
            if b is None and B is None:
                map_control = (-1, 1)
                aff_value = None
            elif b is None:
                map_control = (-1, 0)
                aff_value = (B, 1)
            elif B is None:
                map_control = (0, 1)
                aff_value = (b, 1)
            else:
                map_control = (math.atan(b), math.atan(B))
                aff_value = None
        else:
            raise InvalidCaseError

        # perform conversion
        m, M = self.minimum(), self.maximum()
        if from_control:
            # avoid rounding error when we are on the bounds
            if x == m:
                return b
            elif x == M:
                return B
            # map [m M] onto [0 1]
            x = (x - m) / (M - m)
            # map [0 1] onto map_control
            x = map_control[0] + (map_control[1] - map_control[0]) * x
            # perform nonlinear operation
            if mode == 'log':
                x = math.exp(x)
            elif mode in ['left', 'right', 'middle', 'ext']:
                x = math.copysign(math.pow(abs(x), (1 + strength)), x)
            elif mode == 'tan':
                x = math.tan(math.pi / 2 * x) * strength
            # final affinity to map result onto [b B]
            if aff_value:
                x = aff_value[0] + aff_value[1] * x
            # final corrections
            if self._param_base_cls == pm.Integer:
                x = round(x)
            if b is not None and x < b:
                x = b
            elif B is not None and x > B:
                x = B
        else:
            # initial affinity from [b B]
            if aff_value:
                x = (x - aff_value[0]) / aff_value[1]
            # perform nonlinear operation
            if mode == 'log':
                x = math.log(x)
            elif mode in ['left', 'right', 'middle', 'ext']:
                x = math.copysign(math.pow(abs(x), 1 / (1 + strength)), x)
            elif mode == 'tan':
                x = math.atan(x / strength) / (math.pi / 2)
            # map map_control onto [0 1]
            x = (x - map_control[0]) / (map_control[1] - map_control[0])
            # map [0 1] onto [m M]
            x = round(m + (M - m) * x)

        return x

    def _value_from_control(self):
        return self._slider_conversion(self.value(), from_control=True)

    def _value_edited(self):
        if not self._slider_callback_enabled:
            return
        prev_value = self.parameter_value()
        value = self._value_from_control()
        if value != prev_value:
            self.set_parameter_value(value)
        elif self._param_base_cls == pm.Integer:
            # value is unchanged, but slider position changed and we would
            # like to round it back to the integer marking
            self._display_value(prev_value)

    def _display_value(self, value):
        x = self._slider_conversion(value, from_control=False)

        # update slider display, but prevent its rounding effect to trigger
        # a new value change
        self._slider_callback_enabled = False
        self.setValue(x)
        self._slider_callback_enabled = True

        # update value display
        if self._label_display:
            value_str = text_display(value, self.param)
            txt = self.t_label + translate(': ') + value_str
            self._label_display.setText(txt)

    def _update_text(self):
        super(Slider, self)._update_text()
        if self._label_display:
            self._display_value(self.parameter_value())


class ColorButton(_ColorControlBase, QtWidgets.QLineEdit):

    def _init_control(self):
        if self._control_has_None():
            raise ValueError('color control not available when alllowing None')
        self.setReadOnly(True)
        self.mousePressEvent = self._choose_color

    def _display_value(self, value):
        # value is a 6-char string specifying a 24-bit value in hex
        # format, optionally preceded by a '#', e.g. '#ff0000' for red

        # display coolor name, including QtColor name if it exist,
        # and in any case hex code
        self.setText(text_display(value, self.param))

        # use color for the control background, and make
        # foreground color black or white depending on its luminance
        luminance = np.mean([int(x) for x in bytes.fromhex(value[1:])])
        if luminance > 128:
            foreground = '#000000'
        else:
            foreground = '#ffffff'
        self.setStyleSheet("color:%s; background-color:%s;"
                           % (foreground, value))

    def _update_text(self):
        _ParameterControlBase._update_text(self)
        self._update_value_display()

    def _value_from_control(self):
        value, = re.search('(#\d{6})', self.text()).groups()
        return value

    def setEnabled(self, value):
        # When disabling the control, put background color back to default
        if value:
            self._display_value(self.parameter_value())
        else:
            self.setStyleSheet('')
        super(ColorButton, self).setEnabled(value)


class LineEdit(_ParameterControlBase, QtWidgets.QLineEdit):

    def _init_control(self):
        self.editingFinished.connect(self._value_edited)

        # Detect when text in control is being changed so that
        # editingFinished events will be discarded when there was no change
        self._text_changed = False
        self.textChanged.connect(
            lambda: setattr(self, '_text_changed', True))

    def _value_from_control(self):
        if self._control_has_None() and self.text().lower() == 'None':
            return None
        elif self._param_base_cls == pm.String:
            return self.text()
        elif self._param_base_cls == pm.Integer:
            return int(self.text())
        elif self._param_base_cls == pm.Number:
            return float(self.text())
        elif self._param_base_cls == pm.List:
            items = self.text().split()
            typ = self.param.class_
            # print('list:', items)
            return [typ(x) for x in items]
        else:
            raise InvalidCaseError

    def _value_edited(self, _=None):
        # Was the text really changed?
        if not self._text_changed:
            return
        else:
            self._text_changed = False

        try:
            value = self._value_from_control()
            self.set_parameter_value(value)

        except ValueError:
            # could not interpret text, do not change value and bring back
            # previous display
            expected = translate(
                self._param_base_cls.__name__.replace('param.', ''))
            if self._control_has_None():
                expected += translate('or') + '"None"'
            _error_message(
                translate('Invalid Value, %s expected') % expected)
            self._update_value_display()

    def _display_value(self, value):
        if value is None:
            self.setText('None')
        elif self._param_base_cls == pm.String:
            self.setText(value)
        elif self._param_base_cls in [pm.Integer, pm.Number]:
            self.setText(str(value))
        elif self._param_base_cls == pm.List:
            self.setText(' '.join([str(x) for x in value]))


def parameter_control(obj: pm.Parameterized, name: str, style=None, **kwargs):
    param = obj.param[name]
    param_base_cls = _get_param_base_class(param)

    if param.constant:
        control_cls = ConstantDisplay
    else:
        if style is None and isinstance(param, _GraphicParameter):
            style = param.user['style']
        if param_base_cls == pm.ObjectSelector:
            # There is a list of possible values
            if style == 'button':
                control_cls = CyclingButton
            elif style == 'button-group':
                # remove the do-label and enforce non-multivalues
                if 'do_label' in kwargs:
                    del kwargs['do_label']
                param.user['multivalues'] = False
                control_cls = ButtonGroup
            elif style == 'button-menu':
                if 'do_label' in kwargs:
                    del kwargs['do_label']
                control_cls = ButtonMenu
            else:
                control_cls = PopupMenu
        elif param_base_cls == pm.ListSelector:
            if 'do_label' in kwargs:
                del kwargs['do_label']
            param.user['multivalues'] = True
            control_cls = ButtonGroup
        elif param_base_cls == pm.Boolean:
            if style == 'button':
                control_cls = ToggleButton
            elif style == 'graphic-button':
                # remove the do-label
                if 'do_label' in kwargs:
                    del kwargs['do_label']
                control_cls = GraphicToggleButton
            else:
                control_cls = CheckBox
        elif param_base_cls in [pm.Integer, pm.Number]:
            if style is None:
                if param.bounds is not None and param.bounds[0] is not None \
                        and param.bounds[1] is not None:
                    style = 'slider'
                else:
                    style = 'text'
            if style == 'slider':
                control_cls = Slider
            elif style in ['text', 'edit']:
                control_cls = LineEdit
            else:
                print(style)
                raise InvalidCaseError
        elif param_base_cls == pm.Color:
            control_cls = ColorButton
        elif param_base_cls in [pm.List, pm.String, pm.Color]:
            control_cls = LineEdit
        else:
            raise Exception('No control for parameter of type',
                            param_base_cls)

    return control_cls(obj, name, **kwargs)


# SPECIALIZED MENU CONTROLS


class MenuItem(TranslationProne, QtWidgets.QAction):

    def __init__(self, label, window, callback,
                 checkable=False, dots=False, tooltip=None, **kwargs):

        super(MenuItem, self).__init__(parent=window, **kwargs)

        self._dots = '...' if dots else ''
        self._label = label
        self._tooltip = tooltip

        self.setCheckable(checkable)
        if checkable:
            self.toggled.connect(callback)
        else:
            self.triggered.connect(callback)

        self._update_text()

    def _update_text(self):
        self.setText(translate(self._label) + self._dots)
        # print('action tooltip', translate(self._tooltip))
        self.setToolTip(translate(self._tooltip))


class ToggleMenuItem(_ParameterControlBase, QtWidgets.QAction):

    def __init__(self, window, *args, **kwargs):
        super(ToggleMenuItem, self).__init__(*args, parent=window, **kwargs)

    def _init_control(self):
        self.setCheckable(True)
        self.toggled.connect(self._set_parameter_from_control)

    def _value_from_control(self):
        return self.isChecked()

    def _display_value(self, value):
        self.setChecked(value)

    def _update_text(self):
        self.setText(self.t_label)
        self.setToolTip(self.t_tooltip)


class SelectMenu(_SelectorControlBase, QtWidgets.QMenu):

    def __init__(self, window, *args, **kwargs):
        super(SelectMenu, self).__init__(*args, parent=window, **kwargs)

        # Add watcher on objects
        self.obj.param.watch(self._update_objects_list, self.name,
                             what='names')
        self.obj.param.watch(self._update_value_display, self.name,
                             what='objects')

    def _init_control(self):
        # Create one menu item per possible value
        for label, value, tooltip in zip(self.all_value_names(),
                                         self.all_values(),
                                         self.all_value_tooltips()):
            def callback(checked, val=value):
                # defining an argument with default value is needed to force
                # early binding, otherwise all callback would use the last
                # value in the values list
                # see https://stackoverflow.com/questions/3431676/creating-functions-in-a-loop
                if checked and self.parameter_value() != val:
                    self.set_parameter_value(val)

            action = MenuItem(label, self.parent(), callback, checkable=True,
                              tooltip=tooltip)
            action.setData(value)
            self.addAction(action)

    def _display_value(self, value):
        for action in self.actions():
            action.setChecked(action.data() == value)

    def _update_text(self):
        self.setTitle(self.t_label)
        self.setToolTip(self.t_tooltip)

    def set_visible(self, value):
        # the menu itself is not a graphical element, it is its containing
        # menuAction that must be made visible or not
        self.menuAction().setVisible(value)

    def set_enabled(self, value):
        # the menu itself is not a graphical element, it is its containing
        # menuAction that must be made enabled or not
        self.menuAction().setEnabled(value)


class ControlMenuItem(_ParameterControlBase, QtWidgets.QAction):
    """
    A menu item which, when clicked, will raise a proper control to edit the parameter.
    """

    def __init__(self, window, *args, **kwargs):
        super(ControlMenuItem, self).__init__(*args, parent=window, **kwargs)

    def _init_control(self):
        # callback
        self.triggered.connect(self._raise_control)

        # ... and create a panel control which will be shown only when the
        # menu item will be clicked
        self.control = parameter_control(self.obj, self.name)
        self.control.set_visible = lambda val: None  # set_visible should
        # have no effect on this control, whose visibility will be
        # controlled rather by self (i.e. the ContromMenuItem object)
        self.control.hide()

    def _raise_control(self):
        self.control.show()

    def _display_value(self, value):
        self.setText(translate(self.param.label) + translate(': ')
                     + text_display(value, self.param))

    def _update_text(self):
        self._update_value_display()
        self.setToolTip(translate(self.param.doc))


class ColorMenuItem(ControlMenuItem, _ColorControlBase, QtWidgets.QAction):

    def _init_control(self):
        self.triggered.connect(self._choose_color)


def menu_control(window, obj: pm.Parameterized, name: str, **kwargs):
    param = obj.param[name]
    param_base_cls = _get_param_base_class(param)

    if param.constant:
        raise ValueError('No menu control for constant parameter')
    else:
        # preferred_style = (param.user['style']
        #                    if isinstance(param, GraphicParameter)
        #                    else None)
        if param_base_cls == pm.ObjectSelector:
            control_cls = SelectMenu
        elif param_base_cls == pm.Boolean:
            control_cls = ToggleMenuItem
        elif param_base_cls == pm.Color:
            control_cls = ColorMenuItem
        else:
            control_cls = ControlMenuItem

    return control_cls(window, obj, name, **kwargs)


# ABSTRACT CLASS FOR CONTROL OF MULTIPLE PARAMETERS


class _PanelBase(TranslationProne):

    def _init_panel(self):
        raise NotImplementedError

    def auto_fill(self, obj: Union[pm.parameterized.ParameterizedMetaclass, pm.Parameterized]):
        # Fill the panel by scanning the object's parameters, create
        # sections for nested parameters

        # list of elements to scan
        # Current-level parameters
        for name in obj.param:
            if name == 'name':
                # not interested in 'name' parameter
                continue
            if obj.param[name].user.get('auto_fill', True):
                # use auto_fill=False for a parameter to not be included by
                # auto_fill
                self.add_entry(obj, name)

        # Nested Parameterized objects
        for name, value in obj.__dict__.items():
            if (isinstance(value, pm.parameterized.ParameterizedMetaclass)
                    or isinstance(value, GParameterized)):
                label = (value.label
                         or type(value).__name__.replace('ParamQt.', ''))
                unfolded = not value.start_folded
                self.add_section(label, tooltip=value.doc, unfolded=unfolded)
                self.auto_fill(value)

    def add_section(self, name='', obj=None, names=None,
                    tooltip=None, unfolded=True):
        # Create new section
        section = self._add_section(name, tooltip, unfolded)
        self.current_section = section

        # Add entry(ies) to this section
        if obj is not None:
            self.add_entry(obj, names)

        return section

    def _add_section(self, label, tooltip=None, unfolded=True):
        raise NotImplementedError

    def add_entry(self, obj: pm.Parameterized, names=None, **kwargs):

        # Multiple names? -> return a list of entries
        if names is None:
            self.auto_fill(obj)
        elif not isinstance(names, str):
            for name in names:
                self._add_entry(obj, name, **kwargs)
        else:
            self._add_entry(obj, names, **kwargs)

    def _add_entry(self, obj: pm.Parameterized, name: str, **kwargs):
        raise NotImplementedError

    def add_action(self, label, callback, **kwargs):
        raise NotImplementedError


# QT PANEL FOR CONTROLLING MULTIPLE PARAMETERS


class _Section(TranslationProne):

    def __init__(self, grid, title=None, tooltip=None, unfolded=True, **kwargs):
        # type: (QtWidgets.QGridLayout, str, str, bool, dict) -> None

        super(_Section, self).__init__(**kwargs)

        self.grid = grid
        self.unfolded = unfolded

        # List of widgets (memorize objects to keep them alive)
        self.controls = []
        self.buttons = []

        # List of custom sections if necessary
        self.custom_groups = {}  # type: {str:FlowLayout.FlowLayout}

        # Title
        self.button = None  # type: _FoldingLabel
        self.title = None  # type: QtWidgets.QLabel
        self._title = title
        self._tooltip = tooltip
        if title is not None:
            self._init_title()

    def _init_title(self):
        # Fold/Unfold button
        self.button = _FoldingLabel(self.unfolded)
        self.button.setVisible(
            False)  # visibility will be set to True as soon as some child entries will be added
        self.button.toggle_fold.connect(self.toggle_fold)

        # Title label
        self.title = QtWidgets.QLabel()
        self._update_text()
        self.title.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                 QtWidgets.QSizePolicy.Maximum)
        self.title.mouseReleaseEvent = self.button.mouseReleaseEvent  # quite a hack!

        # Show them
        row = self.grid.rowCount()
        self.grid.addWidget(self.button, row, 0)
        self.grid.addWidget(self.title, row, 1)

    def _update_text(self):
        if self.title is not None:
            self.title.setText(
                '<div style="font-weight: bold; font-size: 10pt;">'
                + translate(self._title) + '</div>')
            self.title.setToolTip(translate(self._tooltip))

    def add_entry(self, obj: pm.Parameterized, names):
        # Multiple names? -> return a list of entries
        if not isinstance(names, str):
            return [self.add_entry(obj, field) for field in names]

        name = names
        control = _SectionControl(obj, name, parent_section=self)
        row = self.grid.rowCount()

        # Check if the control requires itself to be in a custom group
        if control.custom_group is not None:
            # Create the group if necessary
            if control.custom_group not in self.custom_groups:
                self.custom_groups[control.custom_group] = FlowLayout()
                widget = QtWidgets.QWidget()
                widget.setLayout(self.custom_groups[control.custom_group])
                self.grid.addWidget(widget, row, 1, 1, 2)
            # add the control to the group
            self.custom_groups[control.custom_group].addWidget(control.control)
        elif control._label_display is not None:
            self.grid.addWidget(control._label_display, row, 1)
            self.grid.addWidget(control.control, row, 2)
        else:   # cater for label-less elements on a section dialog
            self.grid.addWidget(control.control, row, 1, 1, 2)

        self.controls.append(control)  # keep objects in memory

        # if this is the first "in use" control, this will make the section visible
        self.update_header_visible()

        return control

    def add_action(self, label, action, **kwargs):
        button = _SectionButton(label, action, parent_section=self, **kwargs)
        button.setVisible(self.unfolded)
        row = self.grid.rowCount()
        self.grid.addWidget(button, row, 1, 1, 2)
        self.buttons.append(button)
        self.update_header_visible()
        return button

    def toggle_fold(self):
        self.unfolded = not self.unfolded

        # Change visibility of entries
        for control in self.controls:
            control.update_actual_visible()
        for button in self.buttons:
            button.setVisible(self.unfolded)

    def set_enabled(self, value):
        for control in self.controls:
            control.set_enabled(value)

    def set_visible(self, value):
        for control in self.controls:
            control.set_visible(value)

    def update_header_visible(self):
        if self.button is not None:
            value = any([control.visible for control in self.controls])
            self.button.setVisible(value)
            self.title.setVisible(value)

    def update_display(self):
        for control in self.controls:
            control.entry._update_value_display()


class _SectionElement:
    """A section element has its visibility controlled both by the section
    being folded or unfolded, and its own visibility attribute."""

    def __init__(self, *args, parent_section: _Section = None,
                 visible=True, enabled=True, **kwargs):
        super(_SectionElement, self).__init__(*args, **kwargs)
        self.parent_section = parent_section
        self.visible, self.enabled = visible, enabled
        # hide the control if section is folded, but do not show it
        # explicitly if section is unfolded, as this could show it
        # prematurately
        if not self.parent_section.unfolded:
            self._set_actual_visible(False)

    def set_visible(self, value):
        self.visible = value
        self.update_actual_visible()
        self.parent_section.update_header_visible()

    def update_actual_visible(self):
        actual_visible = self.visible and self.parent_section.unfolded
        self._set_actual_visible(actual_visible)

    def _set_actual_visible(self, actual_visible):
        raise NotImplementedError


class _SectionControl(_SectionElement):
    """A wrapper of _ParameterControl that overrides its set_visible methods."""

    def __init__(self, obj: pm.Parameterized, name: str,
                 parent_section: _Section = None, **kwargs):
        # Control
        self.control = parameter_control(obj, name, do_label=True, **kwargs)
        self._set_actual_visible = self.control.set_visible
        self.control.set_visible = self.set_visible

        # Pass forward if the UI will be grouped together in a custom FlowLayout
        self.custom_group = self.control.param.user.get('custom_group', None)

        # Shortcut on label
        self._label_display = self.control._label_display

        # Section element (must come last because will call
        # update_actual_visible, which needs the control and label to be
        # created)
        _SectionElement.__init__(self, parent_section=parent_section,
                                 visible=self.control.param.visible)

    def update_actual_visible(self):
        value = self.visible and self.parent_section.unfolded
        self._set_actual_visible(value)


class Button(TranslationProne, QtWidgets.QPushButton):

    def __init__(self, label, action, checkable=False, tooltip=None, **kwargs):
        super(Button, self).__init__(**kwargs)
        self.setCheckable(checkable)
        self._label = label
        self._tooltip = tooltip
        self._update_text()
        if checkable:
            self.toggled.connect(action)
        else:
            self.pressed.connect(action)

    def _update_text(self):
        self.setText(translate(self._label))
        self.setToolTip(translate(self._tooltip))

    def set_label(self, label):
        self._label = label
        self._update_text()


class GraphicButton(TranslationProne, QtWidgets.QPushButton):

    def __init__(self, image, label, action, checkable=False, tooltip=None, **kwargs):
        super(GraphicButton, self).__init__(**kwargs)
        self.setCheckable(checkable)
        self._label = label
        self._tooltip = tooltip
        self._update_text()

        self.setIcon(QtGui.QIcon(icon_path(image)))
        self.setIconSize(GRAPHIC_BUTTON_SIZE)

        if checkable:
            self.toggled.connect(action)
        else:
            self.pressed.connect(action)

    def _update_text(self):
        t_label = translate(self._label)
        t_tooltip = translate(self._tooltip)

        if self._tooltip is None:
            self.setToolTip(t_label)
        else:
            self.setToolTip(t_label + '\n' + t_tooltip)

    def set_label(self, label):
        self._label = label
        self._update_text()


class _SectionButton(_SectionElement, Button):

    def _set_actual_visible(self, actual_visible):
        Button.setVisible(actual_visible)


class _FoldingLabel(QtWidgets.QLabel):
    toggle_fold = QtCore.pyqtSignal()

    def __init__(self, unfolded, **kwargs):
        # Create label
        super(_FoldingLabel, self).__init__(**kwargs)
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum,
                           QtWidgets.QSizePolicy.Maximum)

        # Fix size so it won't change when symbole will be changed
        self.setText('>')
        self.size = super(_FoldingLabel, self).sizeHint()

        # Update display according to folding state
        self.unfolded = unfolded
        self.update_display()

    def sizeHint(self):
        # Avoid resizing based on content
        return self.size

    def update_display(self):
        symbol = 'V' if self.unfolded else '>'
        self.setText('<div style="font-weight: bold; font-size: '
                     '10pt;">' + symbol + '</div>')
        self.resize(self.size)  # do not change the size

    def mouseReleaseEvent(self, ev):
        self.unfolded = not self.unfolded
        self.update_display()
        self.toggle_fold.emit()


class ControlPanel(_PanelBase, QtWidgets.QWidget):

    def __init__(self, obj: pm.Parameterized = None, **kwargs):
        super(ControlPanel, self).__init__(**kwargs)

        # 2-columns grid layout + a vertical spacer that maintains the grid
        # on top
        v_layout = QtWidgets.QVBoxLayout()
        self.setLayout(v_layout)
        self.grid = QtWidgets.QGridLayout()
        v_layout.addLayout(self.grid)
        spacer = QtWidgets.QWidget()
        v_layout.addWidget(spacer)

        # List of widgets: organized by sections (first section has no label)
        self.current_section = _Section(self.grid)

        # Then init the parameter control, this might fill the widget if a
        # Paramterized object input is provided
        # automatic layout to control parameter argument
        if obj is not None:
            self.auto_fill(obj)

    def _add_section(self, name, tooltip=None, unfolded=True):
        # Create new section
        return _Section(self.grid, name, tooltip=tooltip, unfolded=unfolded)

    def _add_entry(self, obj: pm.Parameterized, name: str):
        # Add entry(ies) to the current section
        return self.current_section.add_entry(obj, name)

    def add_action(self, label, action, **kwargs):
        return self.current_section.add_action(label, action, **kwargs)


# MENU FOR CONTROLLING MULTIPLE PARAMETERS

class ControlMenu(_PanelBase, QtWidgets.QMenu):

    def __init__(self, window, title,
                 obj: pm.Parameterized = None, **kwargs):
        super(ControlMenu, self).__init__(title='', parent=window, **kwargs)

        # Set translated title
        self._title = title
        self._update_text()

        # Add immediately the menu to the window
        self._window = window
        window.menuBar().addMenu(self)

        # List of entries
        self.entries = []

        # Auto-fill if an object is provided
        if obj is not None:
            if title is None:
                RuntimeError('Please provide a menu title')
            self.auto_fill(obj)

    def _update_text(self):
        self.setTitle(translate(self._title))

    def _add_section(self, label, tooltip=None, unfolded=True):
        # Add section. Note that there is currently no implementation for
        # folding/unfolding.
        self.addSeparator()
        return self.addSection(translate(label))

    def _add_entry(self, obj: pm.Parameterized, name: str, **kwargs):
        entry = menu_control(self._window, obj, name,
                             **kwargs)
        self.entries.append(entry)
        if isinstance(entry, QtWidgets.QMenu):
            self.addMenu(entry)
        else:
            self.addAction(entry)

    def add_action(self, label, callback, **kwargs):
        action = MenuItem(label, self._window, callback,
                          **kwargs)
        self.entries.append(action)
        self.addAction(action)


# DEMO


if __name__ == "__main__":

    pass