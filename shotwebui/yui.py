from shotwebui.controls import Control, LiteralControl
from shotwebui.resources import EnvironObject
from shotlib import json
from urlparse import urljoin

#
# Some YUI-related controls
#

class YuiTracker(EnvironObject):
    def __init__(self, request=None):
        self.depends = set()
        self.base_uri = "/yui"
        self.names = set()
        self.on_load = []

    def require(self, name):
        self.depends.add(name)

    def add(self, func, name=None):
        if name and name in self.names:
            return
        elif name:
            self.names.add(name)
        self.on_load.append(func)

    def create_controls(self, parent):
        result = []
        for f in self.on_load:
            result.append(LiteralControl(parent, value="(function () {"))
            result.extend(f())
            result.append(LiteralControl(parent, value="})();"))
        return result

class YuiLoaderControl(Control):
    preloaded = None
    def do_load(self):
        self.tracker = YuiTracker.get(self.request)
        self._preloaded = set()
        if self.preloaded:
            self._preloaded = set(self.preloaded.split(','))

    def do_create_children(self):
        return []

    def render(self, out):
        # el cheat
        if not self.tracker.depends:
            return
        self.children = self.tracker.create_controls(self)
        self.bind_children()
        if self._preloaded.issuperset(self.tracker.depends):
            out.append("<script>\nYAHOO.util.Event.onDOMReady(function() {")
            super(YuiLoaderControl, self).render(out)
            out.append("});\n</script>")
            return
        subs = {'loader_uri' : urljoin(self.base, "build/yuiloader/yuiloader-beta-min.js"),
                'require' : json.dumps(list(self.tracker.depends)),
                'base_uri' : json.dumps(urljoin(self.base, 'build/'))}
        out.append("""
<script src="%(loader_uri)s"></script>

<script>
 var YUIloader = new YAHOO.util.YUILoader({
    require: %(require)s,
    loadOptional: true,
    base: %(base_uri)s,
    onSuccess: function () {
""" % subs)
        super(YuiLoaderControl, self).render(out)
        out.append("""  }
});
   YUIloader.insert();
</script>
""")

class YuiControl(Control):
    depends = ()
    name = None
    trackerType = YuiTracker
    
    def do_load(self):
        need = [n.strip().lower() for n in self.depends.split(",") if n.strip().lower()]
        tracker = self.trackerType.get(self.request)
        if need:
            for item in need:
                tracker.require(item)
        tracker.add(self.template_body, name=self.name)

    def do_create_children(self):
        return []
