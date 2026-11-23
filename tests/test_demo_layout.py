"""Regresión: los mensajes largos no deben desplazar las acciones fuera de la ventana."""
import tkinter as tk

import pytest

from demo_presentacion import DemoWindow


def assert_visible(widget, window):
    assert widget.winfo_ismapped()
    left, top = widget.winfo_rootx(), widget.winfo_rooty()
    right, bottom = left + widget.winfo_width(), top + widget.winfo_height()
    parent = widget.master
    while parent is not None:
        assert left >= parent.winfo_rootx()
        assert top >= parent.winfo_rooty()
        assert right <= parent.winfo_rootx() + parent.winfo_width()
        assert bottom <= parent.winfo_rooty() + parent.winfo_height()
        if parent is window:
            break
        parent = parent.master


@pytest.mark.parametrize('geometry', ['680x550', '800x600', '1160x678'])
def test_messages_keep_actions_accessible(settings, geometry, tk_window):
    root = tk_window
    app = DemoWindow(root, settings)
    try:
        root.geometry(geometry)
        root.update()
        previous = [(b.winfo_rootx(), b.winfo_rooty()) for b in app.home_actions.buttons]
        app.connection_text.set('AUTHORIZATION_FAILED: revisa los permisos.\n' * 100)
        app.status.set('La tarea se detuvo. Consulta los logs. Código: AUTHORIZATION_FAILED')
        app.show('Detalles del error para consultar en los logs.\n' * 100)
        root.update()
        assert [(b.winfo_rootx(), b.winfo_rooty()) for b in app.home_actions.buttons] == previous
        for button in app.home_actions.buttons + app.footer.buttons:
            assert_visible(button, root)
        assert_visible(app.connection_view, root)
        app.connection_view.yview_moveto(1)
        app.details.yview_moveto(1)
        root.update()
        assert app.connection_view.yview()[1] == 1
        assert app.details.yview()[1] == 1

        app.tabs.select(app.tab_containers[1])
        root.update()
        for button in app.configuration_actions.buttons:
            assert_visible(button, root)
        # El último control y las columnas derechas siguen accesibles al desplazar.
        app.configuration_scroll.canvas.yview_moveto(1)
        app.configuration_scroll.canvas.xview_moveto(1)
        root.update()
        load_button = next(b for b in app.controls if b.cget('text') == 'Cargar configuración')
        assert_visible(load_button, root)

        for container in app.tab_containers[2:]:
            app.tabs.select(container)
            root.update()
            container.canvas.yview_moveto(1)
            container.canvas.xview_moveto(1)
            root.update()
            assert container.canvas.yview()[1] == 1
            assert container.canvas.xview()[1] == 1
            for button in app.footer.buttons:
                assert_visible(button, root)

        app.toggle_presentation()
        root.update()
        assert not app.tabs.winfo_ismapped()
        for button in app.footer.buttons:
            assert_visible(button, root)
        app.show_history()
        root.update()
        assert app.tabs.select() == str(app.tab_containers[5])
    finally:
        app.close()
