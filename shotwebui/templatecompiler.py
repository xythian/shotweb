from __future__ import absolute_import
from shotwebui.controls import Control, ExprControl, html
import shotwebui.templateparser as templateparser
import sys, compiler, os

class SymSource(object):
    def __init__(self):
        self.sym = 0

    def next(self):
        self.sym += 1
        return "sym%d" % self.sym

class CodeEmitter(object):
    enabled = True
    def __init__(self, symsource=None, locals=None, root=None, resolver=None):
        self.body = []
        self.__indent = 0
        if symsource is None:
            self.syms = SymSource()
        else:
            self.syms = symsource
        if locals is None:
            self.locals = {}
        else:
            self.locals = locals
        if root is None:
            self.root = self
            self.resolver = resolver
        else:
            self.root = root
            self.resolver = root.resolver

    def indent(self):
        self.__indent += 3

    def dedent(self):
        self.__indent -= 3
        assert self.__indent >= 0

    def add(self, line, *subs, **ksubs):
        if subs:
            line = line % subs
        elif ksubs:
            line = line % ksubs
        self.body.append((self.__indent, line))
        self.enabled = True

    def createOverride(self, name, args, loc):
        defn = self.createDefn()
        lname = self.defineLocal(loc)
        defn.add("@set_attr(loc=%s)" % lname)
        defn.add("def %s(%s):" % (name, ",".join(args)))
        defn.name = name
        defn.indent()
        defn.enabled = False
        return defn

    def defineBoundProperty(self, name, expr, selfname, loc):
        getter = self.createOverride("_get_%s" % name, (selfname,), loc)
        getter.add("return (%s)" % expr)
        setter = self.createOverride("_set_%s" % name, (selfname, "_v_"), loc)
        setter.add("%s = _v_" % expr)
        self.add("%s = property(_get_%s, _set_%s)" % (name, name, name))
        
    def createClass(self, name, parents, loc):
        defn = self.createDefn()
        defn.add("class %s(%s):" % (name, ",".join(parents)))
        defn.name = name
        defn.indent()
        defn.add("_tmpl_location = %s" % self.defineLocal(loc))
        defn.enabled = False
        return defn


    def createDefn(self):
        defn = CodeEmitter(symsource=self.syms, locals=self.locals, root=self.root)
        self.add(defn)
        return defn

    def defineLocal(self, val):
        # O(n), yuck, but easy and simple
        for k, v in self.locals.items():
            if v is val: return k
        name = self.gensym()
        self.locals[name] = val
        return name

    def generate(self, indentincr=0):
        for indent, line in self.body:
            if isinstance(line, CodeEmitter):
                if line.enabled:
                    for x in line.generate(indentincr + indent):
                        yield x
            else:
                yield "%s%s" % (" " * (indentincr + indent), line)
    def gensym(self):
        return self.syms.next()

def memoize(func):
    import hashlib
    cache = {}
    def _func(template, **kw):
        m = hashlib.md5(template).digest()
        result = cache.get(m)
        if not result:
            result = func(template, **kw)
            cache[m] = result
        return result
    return _func

#class RewriteName(ast.NodeTransformer):
#    def visit_Call(self, node):
#        if isinstance(node.func, ast.Name) and node.func.id == 'ExprControl' and node.keywords and node.keywords[0].arg == 'expression':
#            #print node.func.id, node.keywords[0].value
#            return node
#        else:
#            return self.generic_visit(node)
#    def visit_Name(self, node):
#        return ast.copy_location(ast.Subscript(
#            value=ast.Name(id='data', ctx=ast.Load()),
#            slice=ast.Index(value=ast.Str(s=node.id)),
#            ctx=node.ctx
#            ), node)
            

def generate(template, name=None, kargs=(), resolver=None):
    template = templateparser.parse(template, name=name)
    code = CodeEmitter(resolver=resolver)
    klassname = code.gensym()
    args = ['request']
    args.extend(kargs)
    code.prebinds = code.createDefn()
    code.add("def _resolve(%s):" % ",".join(args))
    code.indent()
    code.bindings = code.createDefn()
    for arg in template.args:
        code.add("%s = request.get_template_arg(%s)", arg, repr(arg))
    klassname = template.emitClassCreate(code, selfname="self")
    code.add("return %s", klassname)
    code.dedent()
    #mcode = "\n".join(code.generate())    
    #myast = ast.parse(mcode)
    #myast = RewriteName().visit(myast)
    return code

def set_attr(loc=None):
    def _wrap(func):
        func._tmpl_location = loc
        return func
    return _wrap

def createset(ctrl, attrs):
    if callable(attrs):
        ctrl._template_attrs = attrs
    elif True:
        ctrl._template_attrs = lambda : attrs
    else:
        for k, v in attrs:
            setattr(ctrl, k, v)
    return ctrl

@memoize
def compile(template, name=None, kargs=(), resolver=None):
    code = generate(template, name=name, kargs=kargs, resolver=resolver)
    text = code.generate()
    globals = code.locals
    globals.update({'ExprControl' : ExprControl,
                    'html' : html,
                    'Control' : Control,
                    'createset' : createset,
                    'set_attr' : set_attr})
    text = list(text)
    text = "\n".join(text)
    if not name:
        name = 'unknown'
    f = compiler.compile(text, name, "exec")
    exec f in globals
    func = globals['_resolve']
    func.source = text
    
    return func

class ControlResolver(object):
    def __init__(self, root=None):
        self.root = root
        self.files = {}

    def resolve_control(self, bindtype='', binding='', request=None):
        return getattr(self, 'resolve_' + bindtype)(request, binding)

    def resolve_environ(self, request, binding):
        # this could easily go awry here, there should be some .. checking
        return request.environ[binding]

    def read_file(self, name):
        f = open(os.path.join(self.root, name), 'rt')
        try:
            return f.read()
        finally:
            f.close()

    def get_template_arg(self, name):
        return None

    def resolve_file(self, request, binding):
        if not self.root:
            return None
        if request is None:
            request = self
        binding = binding + ".ctl"
        result = self.files.get(binding)
        if not result:
            data = self.read_file(binding)
            result = compile(data, name=binding, resolver=self)
            self.files[binding] = (result, data)
        else:
            result = result[0]
        return result(request)



def dump(code):
    text = code.generate()
    for key, val in code.locals.items():
        print "%s = %s" % (key, repr(val))
    for i, line in enumerate(text):
        print "%3d: %s" % (i+1, line)

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option('-l', help="lex", action="store_true", dest="lex", default=False)
    parser.add_option('-s', help="source", action="store_true", dest="source", default=False)
    parser.add_option('-r', help="resolver", action="store", dest="resolver")
    (options, args) = parser.parse_args()
    if not options.resolver:
        resolver = ControlResolver()
    else:
        resolver = ControlResolver(options.resolver)
    for tmpl in [open(arg,'rt').read() for arg in args]:
        if options.lex:
            templateparser._lex(tmpl)
        if options.source:
            code = generate(tmp, resolver=resolverl)
            dump(code)
        else:
            result = compile(tmpl, resolver=resolver)
            print result.source

    
