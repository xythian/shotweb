
# import python's parser to parse exprs
import parser
from controls import LiteralControl
import pprint
  
class Template(object):
    def __init__(self, name='', args=(), contents=()):
        self.args = args
        self.contents = contents
        self.name = name
#        pprint.pprint((name, args, self.contents))
        

    def emitFunction(self, code, name, addlargs=()):
        if addlargs:
            args = []
            args.extend(addlargs)
            args.extend(self.args)
        else:
            args = self.args
        code.add("def %s(%s):", name, ",".join(args))
        code.indent()
        code.add("return [_x(%s) for _x in (%s,)]",
                 args[0],
                 ",".join([item.emitCreate(code) for item in self.contents]))
        code.dedent()


class ControlRef(object):
    def __init__(self, binding, attrs=(), templates=(), args=(), idn=None):
        self.binding = binding
        self.attrs = tuple(attrs)
        self.templates = templates
        self.args = args
        self.idn = idn
        for attr in attrs:
            if attr.name == 'id' and isinstance(attr.val, LiteralExpr):
                self.idn = attr.val.expr

    def emitCreate(self, code, selfname="_"):
        name = self.binding.emitResolve(code)
        if not self.attrs and not self.templates and not self.idn:
            return name
        kname = code.gensym()
        klass = code.createClass(kname, name, self.tmpl_location)
        if self.idn:
            klass.add("def __init__(_, parent, **kw):")
            klass.indent()
            klass.add("super(%s, _).__init__(parent, **kw)", kname)
            klass.add("_.root.ctl_%s = _", self.idn)
            klass.dedent()            
        for template in self.templates:
            template.emitFunction(klass, "template_%s" % template.name, addlargs=(selfname,))
        if self.attrs:
            evalattrs = [attr for attr in self.attrs if not attr.bind]
            bindattrs = [attr for attr in self.attrs if attr.bind]
            if evalattrs:
                binddef = klass.createOverride("_template_attrs", (selfname,), self.tmpl_location)
                binddef.add("return [%s]",
                            ",".join("(%s, %s)" % (repr(attr.name), attr.val.emitEvaluate(binddef)) for attr in evalattrs))
            for bind in bindattrs:
                klass.defineBoundProperty(bind.name, bind.val, selfname, self.tmpl_location)
        return kname

    def __str__(self):
        return "ControlRef(%s, %s)" % (str(self.binding),
                                       ",".join("%s = %s" % (attr.name, attr.val) for attr in self.attrs))

    __repr__ = __str__

class LiteralControlRef(object):
    def __init__(self, value):
        self.value = value

    def emitCreate(self, code):
        return code.defineLocal(LiteralControl.create(self.value))

    def __str__(self):
        return "LiteralControl(%s)" % repr(self.value)

    __repr__ = __str__

class ExprControlRef(object):
    def __init__(self, expr):
        self.expr = expr

    def emitCreate(self, code):
        name = code.gensym()        
        kdef = code.createDefn()
        kdef.add("class %s(ExprControl):", name)
        kdef.indent()
        bindef = kdef.createDefn()        
        bindef.add("def expression(__):")
        bindef.indent()
        bindef.add("return %s", self.expr.emitEvaluate(bindef))
        return name

    def __str__(self):
        return "ExprControlRef(%s)" % str(self.expr)

    __repr__ = __str__
    

class Binding(object):
    def __init__(self, tag, bindtype, binding):
        self.tag = tag
        self.bindtype = bindtype
        self.binding = binding
        self.resolved = None

    def emitResolve(self, code):
        if not self.resolved:
            name = code.gensym()
            code.root.bindings.add("%s = request.resolve_control(bindtype=%s, binding=%s)" % (
                name, repr(self.bindtype), repr(self.binding)))
            self.resolved = name
        return self.resolved

    def __str__(self):
        return "Binding(tag=%s, bindtype=%s, binding=%s)" % tuple(repr(v) for v in (self.tag, self.bindtype, self.binding))

    __repr__ = __str__

class LiteralBinding(object):
    def __init__(self, name):
        self.name = name
        
    def emitResolve(self, code):
        return self.name

class Expr(object):
    def __init__(self, expr):
        self.expr = expr
        self.p = parser.expr(expr.strip())

    def emitEvaluate(self, code):
        return "(%s)" % self.expr

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, repr(self.expr))

    __repr__ = __str__

class LiteralExpr(Expr):
    def __init__(self, value):
        self.expr = value
        self.vname = None
        self.literal = value

    def emitEvaluate(self, code):
        if len(self.expr) < 80:
            return repr(self.expr)
        elif not self.vname:            
            self.vname = code.defineLocal(self.expr)
        return self.vname

class Attr(object):
    def __init__(self, name, val, bind=False):
        self.name = name
        self.val = val
        self.bind = bind

    def __str__(self):
        return "Attr(%s,%s, bind=%s)" % (self.name, str(self.val), repr(self.bind))

