#
# Resource management
#

from controls import Control, LiteralControl

class Resource(object):
    def __init__(self, name, body='', depends=()):
        self.name = name
        self.depends = depends
        self.body = body

class EnvironObject(object):
    envname = 'shotwebui.resourcemanager'    

    @classmethod
    def get(cls, request):
        try:
            return request.environ[cls.envname]
        except KeyError:
            n = cls(request=request)
            request.environ[cls.envname] = n
            return n

    def put(self, request):
        request.environ[self.envname] = self


class ResourceManager(EnvironObject):
    def __init__(self, resources=(), request=None):
        self.resources = {}
        self.registerAll(resources)

    def register(self, resource):
        self.resources[resource.name] = resource

    def registerAll(self, resources):
        for resource in resources:
            self.register(resource)

    def toposort(self, depends):
        sorted = []
        seen = set()
        def visit(name):
            if name in seen:
                return
            seen.add(name)
            resource = self.resources[name]
            for depend in resource.depends:
                visit(depend)
            sorted.append(name)
        for name in depends:
            visit(name)
        return sorted

    def render(self, depends):
        return "".join(self.resources[name].body for name in self.toposort(depends))

class ResourceTracker(EnvironObject):
    envname = 'shotwebui.resourcetracker'
    resourceType = ResourceManager

    def __init__(self, request=None):
        self.request = request
        self._depends = set()
        self.adhoc = []
        self.seen = set()

    @property
    def manager(self):
        return self.resourceType.get(self.request)

    def depends(self, item):
        assert item
        self._depends.add(item)

    def add(self, func, name=''):
        if name and name in self.seen:
            return False
        elif name:
            self.seen.add(name)
        self.adhoc.append(func)
        return True
        

    def create_controls(self, parent):
        body = self.manager.render(self._depends)
        result = []
        if body:
            result.append(LiteralControl(parent, value=body))
        for f in self.adhoc:
            result.extend(f())
        return result

class CSSManager(ResourceManager):    envname = 'shotwebui.resourcemanager.css'
class JavaScriptManager(ResourceManager):    envname = 'shotwebui.resourcemanager.js'
class LinkManager(ResourceManager): envname = 'shotwebui.resourcemanager.links'

class CSSTracker(ResourceTracker):
    envname = 'shotwebui.resourcetracker.css'
    resourceType = CSSManager

class JavaScriptTracker(ResourceTracker):
    envname = 'shotwebui.resourcetracker.js'
    resourceType = JavaScriptManager

class LinkTracker(ResourceTracker):
    envname = 'shotwebui.resourcetracker.links'
    resourceType = LinkManager

class RenderResourceControl(Control):
    trackerType = None

    def do_create_children(self):
        return []

    def render(self, out):
        # el cheat
        self.children = self.trackerType.get(self.request).create_controls(self)
        self.bind_children()
        super(RenderResourceControl, self).render(out)

class ResourceControl(Control):
    trackerType = None

    depends = ""
    name = ""

    def do_load(self):
        need = [n.strip().lower() for n in self.depends.split(",") if n.strip().lower()]
        tracker = self.trackerType.get(self.request)
        if need:
            for item in need:
                tracker.depends(item)
        tracker.add(self.template_body, name=self.name)

    def template_body(self):
        return ()

    def do_create_children(self):
        return []

class RenderJavaScriptControl(RenderResourceControl):  trackerType = JavaScriptTracker
class JavaScriptControl(ResourceControl):              trackerType = JavaScriptTracker

class RenderCSSControl(RenderResourceControl):         trackerType = CSSTracker
class CSSControl(ResourceControl):                     trackerType = CSSTracker

class RenderLinksControl(RenderResourceControl):       trackerType = LinkTracker
class LinkControl(ResourceControl):              trackerType = LinkTracker
