
# shotwebui
#
import sys
from shotwebui.ast import *
import itertools
import re
import bisect

DEBUG = False

DEFN = """
directives   := ws?, '<%@', directive+, '%>'
>directive<  := bind / extends / args / ws
bind         := c'bind', ws, 'tag', equals, qident, ws, resolve
args         := 'args',ws, '(',ws?, (ident, (ws?, ',', ws?, ident)* )?,ws?, ')'
<equals>     := ws?, '=', ws?
resolve      := ident, equals, qident
>qident<     := '"', ident, '"'
extends      := 'extends', ws, resolve
<ws>         := [ \t\r\n]+
ident        := [A-Za-z],[A-Za-z0-9:._]*
"""

DEFN_BODY = """
argslist     := '(',ws?, (ident, (ws?, ',', ws?, ident)* )?,ws?, ')'
<equals>     := ws?, '=', ws?
<ws>         := [ \t\r\n]+
ident        := [A-Za-z],[A-Za-z0-9:._]*
attrlist     := (ws?, ident, ws?, equals, ws?, (string / varref / bindref), ws?)+
defn_begin   := '<def:',ident,ws?,argslist?,ws?,'>'
defn_end     := '</def:',ident,'>'
"""
from simpleparse.stt.TextTools.TextTools import *
from simpleparse.parser import Parser
from simpleparse.common import chartypes, strings
import re
import pprint

WHITESPACE = re.compile(r'^\s+$')

dirparser = Parser(DEFN, 'directives')

class TemplateLocation(object):
   def __init__(self, tmpl, lineno, beg, end, name=None):
      self.tmpl = tmpl
      self.lineno = lineno
      self.name = name
      self.beg = beg
      self.end = end

   @property
   def line(self):
      return self.tmpl[self.beg:self.end]

   def __str__(self):
      return "%s[%d]: %s" % (self.name, self.lineno, self.line)

class REMatch:
   """An object wrapping a regular expression with __call__ (and Call) semantics"""
   def __init__( self, expression, flags=0 ):
      self.matcher = re.compile( expression, flags )
   def __call__( self, text, position, endPosition ):
      """Return new text position, if > position, then matched, otherwise fails"""
      result = self.matcher.match( text, position, endPosition)
      if result:
         return result.end()
      else:
         # doesn't necessarily mean it went forward, merely
         # that it was satisfied, which means that an optional
         # satisfied but un-matched re will just get treated
         # like an error :(
         return position
   def table( self ):
      """Build the TextTools table for the object"""
      return ( (None, Call, self ), )

from simpleparse.dispatchprocessor import dispatch

def treeify(it, pred):
    stack = []
    body = []
    for item in it:
        x, fish = pred(item)
        if x:
            stack.append((x, item, fish, body))
            body = []
        elif stack and stack[-1][0](item):
            _, start, fish, kids = stack.pop()
            kids.append(fish(start, body))
            body = kids
        else:
            body.append(fish(item, ()))
    return body

class ParseException(Exception):
   def __init__(self, name, lineno, error_msg):
      self.lineno = lineno
      super(ParseException, self).__init__("%s, line %d: %s" % (name, lineno, error_msg))

class PageParser(object):
    def __init__(self, tmpl, name=None):
        self.tmpl = tmpl        
        self.binds = {}
        self.args = []
        self.name = name or '<unknown>'
        self.dispatch = {'directives' : self.process_recurse,
                         'args' : self.process_args,
                         'extends' : self.process_extends,
                         'bind' : self.process_bind}
        self.extends = LiteralBinding('Control')
        self.__stack = []
        self.line_positions = list(self.line_parse(tmpl))
        self.line_count = len(self.line_positions)
    
    def to_line(self, pos):
       return bisect.bisect_left(self.line_positions, pos) + 1

    def to_location(self, pos):
       lne = self.to_line(pos)
       if not self.line_positions:
          beg, end = 0, len(self.tmpl)
       else:
          beg = self.line_positions[lne-1]
          end = self.line_positions[lne] if lne < len(self.line_positions) else len(self.tmpl)
       return TemplateLocation(self.tmpl, self.to_line(pos), beg, end, name=self.name)
    
    def line_parse(self, body):
       idx = body.find('\n')
       while idx > 0:
          yield idx
          idx = body.find('\n', idx+1)
       yield len(body) - 1

    def push_control(self, node):
        self.__stack.append(node)

    def pop_control(self):
        self.__stack.pop()

    @property
    def control(self):
        return self.__stack[-1]

    def _tag(self, tag):
        return self.tmpl[tag[1]:tag[2]]
        
    def process_bind(self, beg, end, tags):
        name = self._tag(tags[0])
        bind_type = self._tag(tags[1][3][0])
        bind_name = self._tag(tags[1][3][1])
        self.binds[name] = (bind_type, bind_name)

    def process_extends(self, beg, end, tags):
        typ, name = self._tag(tags[0][3][0]), self._tag(tags[0][3][1])
        self.extends = Binding('', typ, name)
    
    def process_args(self, beg, end, tags):
        self.args = [self._tag(tag) for tag in tags]

    def process_recurse(self, beg, end, tags):
        for tag, beg, end, parts in tags:
            self.dispatch[tag](beg, end, parts)

    def _make_exprcontrol(self, beg, end, parts, children):
        return ExprControlRef(Expr(self.tmpl[beg+3:end-2]))

    def make_body_parser(self):
        chunks = [DEFN_BODY]
        resolvers = []
        ctlnames = []
        disp = {}
        self.dispatch = disp
        for i, (name, (bind_type, bind_name)) in enumerate(self.binds.items()):
            resolvers.append(name)
            ctlnames.append('ctl_single_%d' % i)
            ctlnames.extend(['ctl_begin_%d' % i, 'ctl_end_%d' % i])
            chunks.append("ctl_single_%d := '<%s',ws?,attrlist?,ws?,'/>'" % (i, name))            
            chunks.append("ctl_begin_%d := '<%s',ws?,attrlist?,ws?,'>'" % (i, name))
            chunks.append("ctl_end_%d   := '</%s>'" % (i, name))
            disp['ctl_%d' % i] = self._make_control_parser(Binding(name, bind_type, bind_name))
        ctlnames.extend(['defn_begin', 'defn_end', 'varref', 'printablechar'])
        disp['printable'] = self._make_printable
        disp['varref'] = self._make_exprcontrol
        disp['defn'] = self._make_template
        chunks.append("body  := (%s)+" % ("/".join(ctlnames)))
        return Parser("\n".join(chunks), 'body', prebuilts = [
            ("varref", REMatch("<%#.+?%>").table()),
            ("bindref", REMatch("<%&.+?%>").table())])

    def offset_chunks(self, tags, offset=0):
        for tag, beg, end, parts in tags:
            if parts is None:
                yield (tag, beg + offset, end + offset, parts)
            else:
                yield (tag, beg + offset, end + offset, tuple(self.offset_chunks(parts, offset)))

    def treeify(self, source):
        def _until(tag):
            def _(item):
                return item[0] == tag
            return _
        def _finish(name):
            def _do(start, children):
                return (name, start[1], start[2], start[3], children)
            return _do
        def _func(item):
            tag = item[0]
            if tag == 'defn_begin':
                return _until('defn_end'), _finish('defn')
            elif tag.startswith('ctl_begin_'):
                return _until('ctl_end_%s' % tag[10:]), _finish('ctl_%s' % tag[10:])
            elif tag.startswith('ctl_single_'):
                return False, _finish('ctl_%s' % tag[11:])
            else:
                return False, _finish(tag)
        return treeify(source, _func)

    def condense_chunks(self, tags):
        t = iter(tags)
        chunk_range = None
        while True:
            try:
                tag = t.next()
            except StopIteration:
                break
            if tag[0] == 'printablechar':
                if chunk_range is None:
                    chunk_range = [tag[1], tag[2]]
                else:
                    chunk_range[1] = tag[2]
            else:
                if chunk_range:
                    yield ('printable', chunk_range[0], chunk_range[1], None)
                    chunk_range = None
                yield tag
        if chunk_range:
            yield ('printable', chunk_range[0], chunk_range[1], None)

    def consume_until(self, it, tagname):
        return tuple(itertools.takewhile(lambda x:x[0] != tagname, it))
#        for tag in it:
#            if tag[0] == tagname:
#                return
#            else:
#                yield tag


        return
 

    def _make_printable(self, beg, end, parts, children):
        return LiteralControlRef(self.tmpl[beg:end])

    def _make_template(self, beg, end, parts, children):
        args = ()
        for val in parts:
            if val[0] == 'argslist':
                args = [self._tag(v) for v in val[3]]
        body = []
        for _tag, _beg, _end, _parts, _children in children:
           if _tag == 'defn':
              raise ParseException(self.name, self.to_line(_beg), 
                                   'Bogus defn outside control: %s' % self.tmpl[_beg:end])
           else:
              result = self.do_dispatch(_tag, _beg, _end, _parts, _children)
              body.append(result)
        return Template(name=self._tag(parts[0]), args=args, contents=body)

    strings = strings.StringInterpreter()

    def parse_attrs(self, parts):
        if parts:
            assert parts[0][0] == 'attrlist'
            attrs = []
            it = iter(parts[0][3])
            for name in it:
                val = it.next()
                name = self._tag(name)
                if val[0] == 'string':
                   attrs.append(Attr(name, LiteralExpr(self.strings.string(val, self.tmpl))))
                elif val[0] == 'varref':
                   attrs.append(Attr(name, Expr(self._tag(val)[3:-2])))
                elif val[0] == 'bindref':
                   attrs.append(Attr(name, self._tag(val)[3:-2], bind=True))
            return attrs
        return ()

    def do_dispatch(self, tag, beg, end, parts, children):
       try:
          return self.dispatch[tag](beg, end, parts, children)
       except KeyError:
          raise ParseException(self.name, self.to_line(beg), "Unknown tag: %s <%s>" % (self.tmpl[beg:end], tag))

    def _make_control_parser(self, binding):
        def _parse(beg, end, parts, children):
            tmpls = []
            body = []
            top = ControlRef(binding, attrs=self.parse_attrs(parts), templates=tmpls)
            self.push_control(top)
            top.tmpl_location = self.to_location(beg)
            for _tag, _beg, _end, _parts, _children in children:
               result = self.do_dispatch(_tag, _beg, _end, _parts, _children)
               result.tmpl_location = self.to_location(_beg)
               if _tag == 'defn':
                  tmpls.append(result)
               else:
                  body.append(result)
            self.pop_control()
            if body:
               # ensure body isn't just a bunch of literalcontrols of whitespace
               allfoo = True
               for ctl in body:
                  if not isinstance(ctl, LiteralControlRef):
                     allfoo = False
                  elif not WHITESPACE.match(ctl.value):
                     allfoo = False
               if not allfoo:
                  tmpls.append(Template(name='body', contents=body))
            return top
        return _parse


    def make_ast(self, tags):
        tmpls = []
        body = []
        top = self._make_control_parser(self.extends)(0, 0, (), tags)
        top.args = self.args
        return top
                

    def ppify(self, tpl):
        result = []
        tpl = tuple(tpl)
        for tag, beg, end, parts, children in tpl:
            result.append((tag, self.tmpl[beg:end], parts, tuple(self.ppify(children))))
        return result

    def ppify_flat(self, tpl):
        result = []
        for tag, beg, end, parts in tpl:
            result.append((tag, self.tmpl[beg:end], parts))
        return result
        

    def process(self):
        result = dirparser.parse(self.tmpl)  
        if result[0]:
           for tag, beg, end, parts in result[1]:
             self.dispatch[tag](beg, end, parts)
        bp = self.make_body_parser()
        bodytmpl = self.tmpl[result[2]:]
        bodyparse = bp.parse(bodytmpl)
        results = self.offset_chunks(self.condense_chunks(bodyparse[1]), result[2])
        results = self.treeify(results)
        tpl = tuple(results)
        top = self.make_ast(tpl)
        return top

def parse(tmpl, name=None):
    return PageParser(tmpl, name=name).process()
