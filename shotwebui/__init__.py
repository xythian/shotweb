#
import os
import sys
__all__ = ['compile', 'render']

from templatecompiler import compile

from shotweb import WSGIRequest, environ_property

class ControlResolver(object):
    def __init__(self, root):
        self.root = root
        self.files = {}

    def resolve_control(self, bindtype='', binding='', request=None):
        return getattr(self, 'resolve_' + bindtype)(request, binding)

    def resolve_import(self, request, binding):
        "ew, gross"
        locals = {}
        bits = binding.split('.')
        module = ".".join(bits[:-1])
        kname = bits[-1]
        exec "from %s import %s" % (module, kname) in locals
        return locals[kname]

    def resolve_environ(self, request, binding):
        # this could easily go awry here, there should be some .. checking
        return request.environ[binding]

    def read_file(self, name):
        f = open(os.path.join(self.root, name), 'rt')
        try:
            return f.read()
        finally:
            f.close()

    def resolve_file(self, request, binding):
        binding = binding + ".ctl"
        result = self.files.get(binding)
        if not result:
            data = self.read_file(binding)
            result = compile(data, name=binding)
            self.files[binding] = (result, data)
        else:
            result = result[0]
        return result(request)

class ResourceControlResolver(ControlResolver):
    def read_file(self, name):
        import pkg_resources
        return pkg_resources.resource_string(self.root, name)

class ShotwebUIRequest(WSGIRequest):
    resolver = environ_property('shotweb.ui.resolver',
                                required=False,
                                writable=True,
                                doc="Control resolver for request.")

    def __init__(self, *args):
        super(ShotwebUIRequest, self).__init__(*args)
        if self.resolver is None:
            self.resolver = ControlResolver('./controls')  # current directory root for now
        self.context = {}

    def resolve_control(self, **kwargs):
        return self.resolver.resolve_control(request=self, **kwargs)

    def get_template_arg(self, name):
        return self.context.get(name)
