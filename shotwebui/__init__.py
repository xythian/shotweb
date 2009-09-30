#
import os
import sys
__all__ = ['compile', 'render']

from shotwebui.templatecompiler import compile, ControlResolver
from shotweb import WSGIRequest, environ_property

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
