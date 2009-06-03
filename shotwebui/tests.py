import unittest
from shotwebui import templateparser, templatecompiler


TEST_TEMPLATES = {
    'bind2' : '<%@ bind tag = "abc" import="foobar" %>',
    'binds' : r"""<%@
        args (post)
        bind tag="foo:bar" import="shotweb.ui"
        bind tag="foo:repeater" import="shotweb.ui.pants"
        bind tag="auth:login" environ="shotweb.ui.login.auth" %>
        goober
        """,
    'repeater' : r"""<%@
  args (post)
  bind tag="foo:bar" import="shotweb.ui" 
   bind tag="foo:repeater" import="shotweb.ui.pants" 
    bind tag="auth:login" environ="shotweb.ui.login.auth" %>
<html>
<head>
<title><%# content.title %></title>
<pre>    
   ugly
</pre>
</head>
<body>
<h1><%# content.title %></h1>
<foo:bar name="item" hodor=<%# foo %>>foo <%# hodor %> def</foo:bar>
<def:header()>My header</def:header>
<foo:repeater source=<%# content.items %>>
hi
   <def:item (item)><li><%# item.hodor  %></li></def:item>
</foo:repeater>
<foo:repeater>My <%# body %> is here</foo:repeater>
<ho:dor a="1" />

<auth:login />

<auth:login>
  <template>I like pizza.</template>
</auth:login>
""",
    'shotweb' : """<html>
<head>
<title>ShotWeb</title>
</head>
<body>
<p>If you're reading this, I hope you're either me or Lars.</p>

<p><a href="$script">Here's Shotweb v.current</a></p>

<p><a href="$pydoc">API docs</a></p>

<p>The <a href="$source">source</a> to this shotweb "application".</p>

<dl>
<dt>November 3, 2006</dt>
<dd><ul>
   <li>Lots of rearranging dispatch.</li>
   <li><a href="?dumprequest=1">shotweb.RequestDumper</a></li>
   <li><a href="$redirectdemo">request.redirect(path, perm=False)</a></li>
   <li>request.{app_root,server_uri, absolute_root, full_url(path), full_path(path)}</li>
   <li>A bit of documentation.</li>
   <li>This page.</li>
   </ul></dd>
</dl>
</body>
</html>
"""}

class TestTemplateParser(unittest.TestCase):
    def parse(self, tmpl, name=None):
        return templateparser.parse(TEST_TEMPLATES[tmpl], name=name)

    def testbinds(self):        
        result = self.parse('binds')
        print result

    def testbinds2(self):
        result = self.parse('bind2')

    def testrepeater(self):
        result = self.parse('repeater')
        print result

    def testshotweb(self):
        result = self.parse('shotweb')
        print result

def dumptext(txt):
    for i, line in enumerate(txt.split("\n")):
        print "%3d: %s" % (i+1, line)

class TestCompiler(unittest.TestCase):
    def generate(self, tmpl, name=None):
        code = templatecompiler.generate(TEST_TEMPLATES[tmpl], name=name)
        return code

    def testall(self):
        for key in TEST_TEMPLATES.keys():
            code = self.generate(key)
            dumptext(TEST_TEMPLATES[key])
            templatecompiler.dump(code)
    

if __name__ == '__main__':
    unittest.main()
