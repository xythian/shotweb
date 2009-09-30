"A few basic control types."
import time
from cgi import escape as escape_
import re
from itertools import chain
from urlparse import urljoin

from shotweb import demandprop

class html(unicode):
    pass

def escape(val, quote=False):
    return escape_(val, quote=True)

class IdSource(object):
    def __init__(self, pat="clientid%d"):
        self.count = 0
        self.pat = pat

    def next(self):
        try:
            return self.pat % self.count
        finally:
            self.count += 1


class Control(object):
    children = ()
    container_element = None
    container_attributes = ()
    implements_bind_create = False
    immediate_attribute_bind = ()

    def __init__(self, parent, request=None):
        self.parent = parent
        if request is None:
            self.request = parent.request
        else:
            self.request = request
        self.init()

    def init(self):
        pass

    def bind(self):
        self.do_bind()
        self.do_load()
        self.create_children()

    def parents(self):
        parent = self.parent
        while parent != None:
            yield parent
            parent = parent.parent

    @demandprop
    def root(self):
        if self.parent:            
            return list(self.parents())[-1]
        else:
            return self

    @demandprop
    def idsource(self):
        if self == self.root:
            return IdSource()
        else:
            return self.root.idsource

    @demandprop
    def clientid(self):
        return self.idsource.next()

    def _template_attrs(self):
        return ()

    def do_bind(self):
        for name, val in self._template_attrs():
            setattr(self, name, val)

    def do_load(self):
        pass

    def dump(self):
        p = self.__class__
        while p.__name__.startswith('sym'):
            p = p.__bases__[0]
        if hasattr(self, '_tmpl_location'):
            return "%s (%s)" % (p.__name__, str(self._tmpl_location))
        else:
            return p.__name__

    def template_body(self):
        return []

    def do_create_children(self):
        return self.template_body()

    def create_children(self):
        self.children = self.do_create_children()
        self.bind_children()

    def bind_children(self):
        for child in self.children:
            child.bind()

    def respond(self):
        self.bind()        
        return self.do_render()

    def do_render(self):
        out = []
        self.render(out)
        return [u"".join(out)]

    def render_attributes(self, out):
        out.extend(' %s="%s"' % (name, escape(val)) for name, val in self.container_attributes)

    def render_element(self, out, body):
        elt = self.container_element
        if elt is not None:
            out.append("<%s" % self.container_element)
            self.render_attributes(out)
            out.append(">")
        body(out)
        if elt is not None:
            out.append("</%s>" % elt)

    def render_children(self, out):
        for child in self.children:
            child.render(out)

    def render(self, out):
        self.render_element(out, self.render_children)

class ControlGenerator(Control):
    implements_bind_create = True
    @classmethod
    def emitBindCreate(cls, code, cref, pname=None, append=None):
        cref.emitCreate(code, append, pname)

class ExprControl(Control):
    def __init__(self, *args, **kwargs):
        if kwargs.get('expression') is not None:
            self.expression = kwargs['expression']
            del kwargs['expression']
        super(ExprControl, self).__init__(*args, **kwargs)
        
    @demandprop
    def value(self):
        return self.expression()

    def expression(self):
        "This is overriden in compiler."
        return html('')        

    def render(self, out):
        val = self.value
        if not isinstance(self.value, basestring):
            val = unicode(val)
        out.append(escape_if_needed(val))

def escape_if_needed(value):
    if isinstance(value, html):
        return value
    elif not isinstance(value, basestring):
        return escape(unicode(value))
    else:
        return escape(value)

class LiteralControl(object):
    __slots__ = ('value',)
    def __init__(self, parent=None, value=''):
        self.value = value

    def bind(self):
        pass
        
    @classmethod
    def create(cls, text):
        # violates contract, we'll see if this flies
        return cls(value=text)

    def render(self, out):
        out.append(self.value)

class ShowTree(Control):
    def traverse(self, root, indent, dedent):
        yield root
        indent()
        for child in root.children:
            for kid in self.traverse(child, indent, dedent):
                yield kid
        dedent()
    def render(self, out):    
        root = self.root
        result = []
        def indent():
            result.append("<ul>")
        def dedent():
            result.append("</ul>")
        indent()
        for node in self.traverse(root, indent, dedent):
            result.append("<li>%s</li>" % escape(node.dump()))
        dedent()
        out.append(html("".join(result)))

class DropDownControl(Control):
    source = ()
    value = None
    name = None

    def render(self, out):
        out.append('<select name="%s">' % self.name)
        def checked(value):
            if value == self.value: return ' selected'
            return ''
        out.extend('<option value="%s"%s>%s</option>' % (value, checked(value), escape(desc)) for value, desc in self.source)
        out.append('</select>')


class PlaceholderControl(Control):
    name = 'placeholder'

    def create_children(self):
        result = None
        looked = []
        for parent in chain([self], self.parents()):
            looked.append(parent)
            if hasattr(parent, 'template_' + self.name):
                result = getattr(parent, 'template_' + self.name)()
                break
        if result is None:
            result = [LiteralControl(self,
                                     value='No binding for %s found (looked at %s)' % (self.name,
                                                                                       escape(str(looked))))]
        self.children = result
        self.bind_children()

class IfControl(ControlGenerator):
    expr = False

    @classmethod
    def emitBindCreate(cls, code, cref, pname=None, append=None):
        #if cls is not IfControl:
        #    return ControlGenerator.emitBindCreate(cls, code, pname=pname, append=append)
        body_tmpl = cref.findTemplate('body')
        else_tmpl = cref.findTemplate('else')
        expr = cref.findAttribute('expr')
        code.add("# IfControl %s:%d", cref.tmpl_location.name, cref.tmpl_location.lineno)
        if (not body_tmpl and not else_tmpl) or not expr:
            return
        if body_tmpl:
            code.add("if %s:", expr.val.emitEvaluate(code))
            code.indent()
            body_tmpl.emitInline(code, append, pname)
            code.dedent()
            if else_tmpl:
                code.add("else:")
                code.indent()
                else_tmpl.emitInline(code, append, pname)
                code.dedent()
        elif else_tmpl:
            code.add("if not %s:", expr.val.emitEvaluate(code))
            code.indent()
            else_tmpl.emitInline(code, append, pname)            
            code.dedent()

    def do_create_children(self):        
        if self.expr:
            return self.template_body()
        elif hasattr(self, 'template_else'):
            return self.template_else()
        else:
            return ()

#    def bind(self):
#        if not self.bound:
#            super(IfControl, self).bind()

class RepeaterControl(ControlGenerator):
    @classmethod
    def emitBindCreate(cls, code, cref, pname=None, append=None):
        if cls is not RepeaterControl or not cref.findTemplate('item'):
            ControlGenerator.emitBindCreate(cls, code, pname=pname, append=append)
        item_tmpl = cref.findTemplate('item')
        source = cref.findAttribute('source')
        gsm = code.gensym()
        funcname = item_tmpl.emitAppendFunction(code, pname)
        code.add("for %s in %s:", gsm, source.val.emitEvaluate(code))
        code.indent()
        code.add("%s(%s, %s)", funcname, append, gsm)
        code.dedent()
    
    def template_item(self, item):
        return ()
    def create_children(self):
        self.children = []
        for item in self.source:
            self.children.extend(self.template_item(item))
        self.bind_children()

def intprop(name, doc='', default=0):
    def _get(self):
        try:
            return getattr(self, name)
        except AttributeError:
            return default

    def _set(self, v):
        if v is None:
            v = 0
        elif type(v) is not int:
            v = int(v)
        setattr(self, name, v)
    return property(_get, _set, doc=doc)

class PageEntry(object):
    def __init__(self, name='', current=False, href=''):
        self.name = name
        self.current = current
        self.href = href

class WrapperControl(Control):
    wrap = True
    condition = True
    text = ""

    def template_prefix(self):
        return ()

    def template_suffix(self):
        return ()

    def template_body(self):
        return [LiteralControl(self, self.text)]

    def do_create_children(self):
        if not self.condition:
            return ()
        elif self.wrap:
            return list(chain(self.template_prefix(), self.template_body(), self.template_suffix()))
        else:
            return self.template_body()

class ControlDefinitionException(Exception):
    pass

PAGE_M = re.compile(r'/page/(\d+)')
class PaginatorControl(Control):
    __name = None

    def _set_name(self, name):
        setattr(self.root, name, self)
        self.__name = name
    def _get_name(self):
        return self.__name

    name = property(_get_name, _set_name)
    page = intprop('_page', default=-1)
    pagesize = intprop('_pagesize', default=24)

    source = ()

    def do_load(self):
        source = self.request.uri
        path = PAGE_M.sub('/', source)
        if not path.endswith('/'):
            path += '/'
        if self.page < 0:
            # unset, figure it out
            try:
                page = self.request.urlmatch.group('page')
                if not page:
                    page = 0
                else:
                    page = int(page)
            except IndexError:
                page = 0
            self.page = page
        def plink(p):
            val = urljoin(path, 'page/%d' % p) if p else path
            if self.request.query_string:
                val += '?' + self.request.query_string
            return val
        self.pagelink = plink
        # doing this before referencing .pages or .count allows
        # an optimization when the underlying source is a virtual sequence
        # backed by a database (it can fetch the count and items in one call)
        # because it knows the start and end items
        self.items = self.source[self.startitem:self.enditem]

    @property
    def count(self):
        return len(self.source)

    @property
    def pages(self):
        pages = self.count / self.pagesize
        if pages * self.pagesize < self.count:
            pages += 1
        return pages

    @property
    def pageno(self):
        return self.page + 1

    @property
    def startitem(self):
        return self.page * self.pagesize

    @property
    def enditem(self):
        return self.startitem + self.pagesize
    
    @property
    def hasnext(self):
        return self.page < self.pages - 1

    @property
    def nextpage(self):
        if self.page < self.pages - 1:
            return PageEntry(self.page+2, current=False, href=self.pagelink(self.page+1))
        else:
            return None

    @property
    def hasprev(self):
        return self.page > 0

    @property
    def prevpage(self):
        if self.page > 0:
            return PageEntry(self.page, current=False, href=self.pagelink(self.page-1))
        else:
            return None

    @property
    def pageitems(self):
        pagelink = self.pagelink
        if self.pages <= 13:
            for i in xrange(self.pages):
                current = self.page == i
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
        elif self.page <= 7:
            for i in xrange(9):
                current = self.page == i
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
            yield PageEntry('. . .')
            for i in xrange(self.pages - 3, self.pages):
                current = self.page == i
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
        elif self.page >= (self.pages - 8):
            for i in xrange(4):
                current = self.page == i
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
            yield PageEntry('. . .')
            for i in xrange(self.pages - 9, self.pages):
                current = self.page == i
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
        else:
            for i in xrange(4):
                current = self.page == i
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
            yield PageEntry('. . .')
            for i in xrange(self.page - 3, self.page + 3):
                current = self.page == i                
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
            yield PageEntry('. . .')
            for i in xrange(self.pages - 3, self.pages):
                current = self.page == i                
                yield PageEntry(str(i+1), current=current, href=pagelink(i))
    
