"""Touch-friendly native chooser, shown before the browser starts."""
def choose_system():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    chosen = [None]
    window = Gtk.Window(title="Little Macintosh")
    window.set_default_size(420, 260)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.set_border_width(20)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    window.add(box)
    title = Gtk.Label(label="Choose a Macintosh system")
    title.set_markup('<span size="x-large" weight="bold">Choose a Macintosh system</span>')
    box.pack_start(title, False, False, 4)

    def select(_button, value):
        chosen[0] = value
        Gtk.main_quit()

    for label, value in (("System 7.5.3", "system-7"), ("Mac OS 8.0", "mac-os-8.0"), ("Mac OS 8.5", "mac-os-8.5"), ("BeOS Release 3", "beos")):
        button = Gtk.Button(label=label)
        button.set_size_request(-1, 60)
        button.connect("clicked", select, value)
        box.pack_start(button, True, True, 0)
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", select, None)
    box.pack_start(cancel, False, False, 0)
    window.connect("destroy", lambda _window: Gtk.main_quit())
    window.show_all()
    Gtk.main()
    window.destroy()
    return chosen[0]
