"""Shotweb

It's a way to make python scripts into web applications.

"""
__version__ = "0.5"
__all__ = ['WSGIRequest', 'run', 'debug_error_handler', 'production_error_handler', 'shotauth']


import os
#
#
# Most of the API for shotweb
#    shotweb is a mix of the web "framework" that grew around Singleshot
#    and parts of web.py that I liked
#
import sys
import re
import cgitb
import cgi
import os
import mmap

import hmac, hashlib
import time
import base64
import struct
import logging

from itertools import chain
from urllib import quote
from urlparse import urljoin, urlparse
from Cookie import SimpleCookie
from BaseHTTPServer import BaseHTTPRequestHandler
from datetime import datetime, timedelta
from functools import wraps
import sys
import wsgiref.util

RESPONSES = BaseHTTPRequestHandler.responses

class EndRequestException(Exception):
    "Raise this in a request handler to end the request and LEAP as if from guns back up to the WSGI wrapper."
    def __init__(self, reason=None, code=500, headers=(),body=()):
        self.reason = reason
        self.code = code
        self.body = body
        self.headers = headers

    def status_line(self):
        return "%d %s" % (self.code, RESPONSES[self.code])


class RedirectException(EndRequestException):
    "It's just less confusing if .redirect ends the request."
    pass

class ShotWebFileWrapper(object):
    "Internal class used (only) by shotweb to communicate to itself that a response should be a file contents."
    
    def __init__(self, f, chunksize=1024*7):
        self._f = f
        self.__chunksize = chunksize

    def __iter__(self):
        data = self._f.read(self.__chunksize)
        while data:
            yield data
            data = self._f.read(self.__chunksize)
        del self._f

    def close(self):
        if hasattr(self, '_f'):
            del self._f

def demand_property(name, loadfunc):
    def _get_demand_property(self):
        try:
            return getattr(self, '_%s_value' % name)
        except AttributeError:
            v = loadfunc(self)
            setattr(self, '_%s_value' % name, v)
            return v
    def _flush_demand_property(self):
        try:
            delattr(self, '_%s_value' % name)
        except AttributeError:
            # ok, not loaded
            pass
        
    return property(_get_demand_property, None, _flush_demand_property, doc=loadfunc.__doc__)

def demandprop(func):
    return demand_property(func.__name__, func)

class AutoPropertyMeta(type):
    def process_properties(cls, name, bases, dict):
        for key, val in dict.items():
            if key.startswith('_get_') and callable(val):
                pname = key[5:]
                if dict.has_key(pname):
                    continue
                getter = val
                if dict.has_key('_set_' + pname):
                    setter = dict['_set_' + pname]
                    prop = property(getter, setter)
                else:
                    prop = property(getter)
                dict[pname] = prop
            elif key.startswith('_load_') and callable(val):
                pname = key[6:]
                if dict.has_key(pname):
                    continue
                dict[pname] = demand_property(pname, val)
    process_properties = classmethod(process_properties)
    def __new__(cls, name, bases, dict):
        cls.process_properties(name, bases, dict)
        return super(AutoPropertyMeta, cls).__new__(cls, name, bases, dict)


def handle_404(environ, start_response):
    start_response("404 Not Found", [("Content-type", "text/html")])
    return ['Page not found']

def wsgi_redirect(environ, start_response, url, code=302):
    "Immediately end the request and send a redirect (301 if perm, 302 otherwise) to path."
    if url[0] == '/':
        url = url[1:]
    location = urljoin(wsgiref.util.application_uri(environ), url)
    start_response("%d %s" % (code, RESPONSES[code]),
                   [("Content-type", "text/html"),
                    ("Location", location)])
    return ['Please see <a href="%s">%s</a>.' % (location, location)]
            
HTTP_METHODS = ('GET', 'HEAD', 'PUT', 'DELETE', 'OPTIONS', 'TRACE', 'POST')

def environ_property(name, default=None, required=True, writable=False, doc=''):
    if required:
        def _get(self):
            return self.environ[name]
        doc += " (always present)"
    else:
        def _get(self):
            return self.environ.get(name, default)
        doc += " (default: %s)" % repr(default)
    if writable:
        def _set(self, v):
            self.environ[name] = v
        def _del(self):
            del self.environ[name]
        doc += " (read/write)"    
        return property(_get, _set, _del, doc=doc)
    else:
        doc += " (read only)"
        return property(_get, doc=doc)

def proxy_root_middleware(uri):
    scheme, netloc, path, params, query, fragment = urlparse(uri)
    http_host = netloc
    if netloc.find(':') > 0:
        host, port = netloc.split(':')
    else:
        host = netloc
        if scheme == 'https':
            port = "443"
        else:
            port = "80"
    if path == '/':
        path = ""
    def proxy_root(app):
        def handle(environ, start_response):
            environ["SERVER_NAME"] = host
            environ["SERVER_PORT"] = port
            environ["SCRIPT_NAME"] = path
            environ["HTTP_HOST"] = http_host
            return app(environ, start_response)
        return handle
    return proxy_root

class WSGIRequest(object):
    "Represents a request (and a response) to a shotweb request."
    __metaclass__ = AutoPropertyMeta


    def __init__(self, urlmatch, environ, start_response):
        """Shotweb creates a request with some stuff

         urlmatch -- the true value that the url matcher returned.  In the case of regexp URL patterns this will be t he match object.

        """
        self._urlmatch = urlmatch
        self.__start = start_response
        self.environ = environ
        if not environ.has_key('shotweb.response.headers'):
            environ['shotweb.response.headers'] = []
        self._header_hooks = []
        if not environ.has_key('shotweb.cookie'):
            self.cookie = SimpleCookie()
            try:
                self.cookie.load(environ['HTTP_COOKIE'])
            except KeyError:
                # no cookie
                pass

    def _load_form(self):
        "Create a cgi.FieldStorage from self.input and self.environ.  Consumes self.input."
        return cgi.FieldStorage(fp=self.input,
                                environ=self.environ)

    def n(s):
        return "shotweb.response.%s" % s

    cookie = environ_property('shotweb.cookie', writable=True,
                              doc="""A SimpleCookie object loaded with the HTTP_COOKIE for this request.""")

    def _get_urlmatch(self):
        "Returns the match object from the URL matcher."
        return self._urlmatch


    remote_user = environ_property('REMOTE_USER', writable=True, required=False,
                                   doc="CGI REMOTE_USER environmental variable.")

    content_type = environ_property(n('content_type'), required=False, default='text/html', writable=True,
                                    doc="Content-type for the response")
    content_length = environ_property(n('content_length'), required=False, default=0, writable=True,
                                      doc="Content-length for the response")
    sent_headers = environ_property(n('sent_headers'), required=False, default=False, writable=True,
                                    doc="Have headers been sent yet?  Boolean")
    response_code = environ_property(n('response.code'), required=False, default=200, writable=True,
                                     doc="Response code for response")
    headers = environ_property(n('headers'),
                               doc="Headers for response.  List of (header, value).")

    del n

    scheme = environ_property('wsgi.url_scheme', doc="HTTP scheme (http/https) used to access app.")
    host = environ_property('HTTP_HOST', doc="Host used to access app (Host: or SERVER_NAME header).")
    errors = environ_property('wsgi.errors', doc="File-like object for accessing stderr for request.")
    input = environ_property('wsgi.input',
                             doc="""File-like object for reading stdin for request
                             (use is mutually exclusive with using request.form""")
    method = environ_property('REQUEST_METHOD', doc="HTTP METHOD used for this request.")
    path_info = environ_property('PATH_INFO', doc="PATH_INFO for request.", required=False, default='')

    remote_addr = environ_property('REMOTE_ADDR', doc="IP address of remote user.")

    def _get_uri(self):
        "Request URI"
        return wsgiref.util.request_uri(self.environ)

    server_name = environ_property('SERVER_NAME', doc="SERVER_NAME for request")
    query_string = environ_property('QUERY_STRING', default='', required=False, doc="QUERY_STRING for request.")
    
    def _get_host(self):
        "HTTP_HOST (if present)or SERVER_NAME"
        # can't use environ_property because we want a computed default
        return self.environ.get('HTTP_HOST', self.server_name)

    def _get_port(self):
        "(int) SERVER_PORT"
        # can't use e_p because want to int the result
        return int(self.environ['SERVER_PORT'])

    def _get_app_root(self):
        "Application root -- the part of the URI path used to access the script."
        val = self.environ['SCRIPT_NAME']
        if not val:
            return '/'
        else:
            return val

    def _get_absolute_root(self):
        "Server URI + application root -- absolute root of application"
        return wsgiref.util.application_uri(self.environ)        

    def __update_headers(self):
        hdrs = self.headers
        has_ct = [h[1] for h in hdrs if h[0] == 'Content-type']
        has_cl = [h[1] for h in hdrs if h[0] == 'Content-length']
        if not has_ct:
            hdrs.append(('Content-type', self.content_type))
        if not has_cl and self.content_length:
            hdrs.append(('Content-length', str(self.content_length)))

    def header_hook(self, func):
        self._header_hooks.append(func)

    def run_header_hooks(self):
        for hook in self._header_hooks:
            hook(self.headers)

    def send_headers(self):
        """Send the headers for this request, if they haven't been sent.
        
        This is called automatically when the request handler returns.  It is unlikely an application author would need to call this directly.
        """
        if not self.sent_headers:
            self.sent_headers = True
            self.run_header_hooks()
            self.__update_headers()
            status = '%d %s' % (self.response_code, RESPONSES[self.response_code][0])
            self.__write = self.__start(status, self.headers)

    def wsgi_pass(self, app):
        "Pass control to the given WSGI app without writing any headers of our own.   Must be called before .send_headers."
        "Should be called with 'return request.wsgi_pass(app)' so the return value propagates correctly."
        assert not self.sent_headers
        self.sent_headers = True
        return app(self.environ, self.__start)

    def write(self, bytes):
        """Write bytes out as the response.   This will send the headers if they haven't already been sent.

        It's best to return an iterable from the handler rather than using this.
        """
        if not self.sent_headers:
            self.send_headers()
        self.__write(bytes)

    def respond_file(self, path, content_type):
        "Returns an object to send the contents of the given file as the given content-type."
        l = os.stat(path).st_size
        self.content_type = content_type
        self.content_length = l
        return ShotWebFileWrapper(open(path))

    def full_url(self, path):
        """Combine path with .absolute_root to form a fully qualified URI to path.

        Path is assumed to be rooted at the application root."""
        if path[0] == '/':
            path = path[1:]
        return urljoin(self.absolute_root, path)

    def full_path(self, path):
        "Combine path with .app_root to form a fully qualified URI to path."
        if path and path[0] == '/':
            path = path[1:]
        root = self.app_root
        if not root or root[-1] != '/':
            root = root + '/'
        return urljoin(root, path)

    def redirect(self, path, perm=False):
        "Immediately end the request and send a redirect (301 if perm, 302 otherwise) to path."
        if perm:
            code = 301
        else:
            code = 302
        path = str(self.full_url(path))
        self.content_type = 'text/html'
        body = 'Please see <a href="%s">%s</a>.' % (path, path)
        self.content_length = len(body)
        self.run_header_hooks()
        self.__update_headers()
        self.headers.append(('Location', path))
        raise RedirectException(reason="Redirect.",
                                code=code,
                                body=(body,),
                                headers=self.headers)

    def dump(self):
        "Returns a list of (key, val) pairs describing lots of request state."
        r = [(key, str(val)) for key, val in self.environ.items()]
        r.extend(("request.form[%s]" % repr(key), repr(self.form[key])) for key in self.form)
        for prop in ('scheme', 'host', 'method', 'path_info', 'uri', 'host', 'server_name', 'port', 'query_string', 'app_root', 'absolute_root'):
            r.append(("request.%s" % prop, str(getattr(self, prop))))
        return r                                

    def html_dump(self):
        ".dump() formatted as an HTML table"
        body = ("<tr><td>%s</td><td>%s</td></tr>" % (cgi.escape(key), cgi.escape(val)) for key, val in self.dump())
        return '<table border="1" width="100%%">%s</table>' % "\n".join(body)

    def plain_dump(self):
        ".dump() formatted as plain text"
        return "\n".join("%s = %s" % (key, val) for key, val in self.dump())

    def log(self, message, *args, **kwargs):
        "Log a line to stderr for the request"
        if args:
            message = message % args
        elif kwargs:
            message = message % kwargs
        self.errors.write("<shotweb> %s\n" % message)

def by2(itr):
    if not hasattr(itr, 'next'):
        itr = iter(itr)
    while True:
        yield (itr.next(), itr.next())

def debug_error_handler(environ, start_response):
    """Log exceptions while also dumping detailed (and potentially dangerous!) information the web user.

    This and its companion, production_error_handler, are intended to be passed to run() as the error_handler argument.
    """
    exc_info = environ.get('com.xythian.shotweb.exception')
    write = start_response('500 Internal server error',
                           [('Content-type', 'text/html')],
                           exc_info)
    et, v, tb = exc_info
    import traceback
    traceback.print_exception(et, v, tb, file=sys.stderr)
    return cgitb.html(exc_info)

def production_error_handler(environ, start_response):
    "Log exceptions while limiting information shown to the web user."
    exc_info = environ.get('com.xythian.shotweb.exception')
    write = start_response('500 Internal server error',
                           [('Content-type', 'text/html')],
                           exc_info)
    return ['An error has occured.']

def capture_exceptions(app, error_handler):
    "(middleware) Capture exceptions escaping from app() and pass control if one occurs to error_handler."
    def handle(environ, start_response):
        try:
            return app(environ, start_response)
        except:
            environ['com.xythian.shotweb.exception'] = sys.exc_info()
            try:
                return error_handler(environ, start_response)
            finally:
                try:
                    del environ['com.xythian.shotweb.exception']
                except KeyError:
                    pass
    return handle

def methods_for(handler):
    methods = HTTP_METHODS
    if hasattr(handler, 'HTTP_METHODS'):
        methods = handler.HTTP_METHODS
    elif hasattr(handler, 'http_methods'):
        methods = handler.http_methods
    if callable(handler):
        return [(method, handler) for method in methods]
    elif hasattr(handler, 'service'):
        return [(method, handler.service) for method in methods]
    else:
        return [(method, getattr(handler, 'do_' + method)) for method in methods if hasattr(handler, 'do_' + method)]

def re_matcher(pattern):
    pattern = re.compile('^' + pattern + '$').match
    def _matcher(s, environ):
        return pattern(s)
    return _matcher

def wrap_handlers(handlers, wrap):
    h = iter(handlers)
    while True:
        yield h.next()
        yield wrap(h.next())
    

def make_wsgi(urls, unknown_handler, requestType=WSGIRequest):
    dispatch = dict((method, []) for method in HTTP_METHODS)
    for pattern, handler in urls:
        if callable(pattern):
            match = pattern
        else:
            match = re_matcher(pattern)
        for method, func in methods_for(handler):
            dispatch[method].append((match, func))
    def wsgi_adapter(environ, start_response):        
        path = environ.get('PATH_INFO', '')
        if path.find('?') > 0:
            path = path[:path.find('?')]        
        method = environ['REQUEST_METHOD']
        for matcher, handler in dispatch.get(method, ()):
            m = matcher(path, environ)
            if m:            
                request = requestType(m, environ, start_response)
                try:
                    result = handler(request)
                    if not request.sent_headers:
                        request.send_headers()
                    return result
                except EndRequestException, v:
                    w = start_response(v.status_line(), v.headers)
                    return v.body
        return unknown_handler(environ, start_response)
    return wsgi_adapter

def querystring_condtional(name):
    t = '%s=1' % name
    def test(environ):
        return environ.get('QUERY_STRING', '').find(t) > -1
    return test

def RequestDumper(parameter='dumprequest', requestType=WSGIRequest, log=False):
    test = parameter
    if not callable(test):
        test = querystring_condtional(test)        
    def _middleware(app):
        def _handle(environ, start_response, exc_info=None):
            result = app(environ, start_response)
            request = requestType(None, environ, start_response)
            if test(environ):
                if log:
                    logging.getLogger('shotweb.requestdump').debug(request.plain_dump())
                if request.content_type.startswith('text/plain'):
                    return chain(result, [request.plain_dump()])
                elif request.content_type.startswith('text/html'):
                    return chain(result, [request.html_dump()])
            return result
        return _handle
    return _middleware

def shotauth_wrapper(secretsource, valid_duration=timedelta(days=365), name='TKT', domain=None, path='/'):
    """Returns a Shotweb request handler wrapper that performs as the middleware function except exposes
       the API as request.shotauth rather than the environment.   This is better integrated with shotweb."""
    SignedCookie, AuthService = shotauth_make(secretsource,
                                              valid_duration,
                                              name,
                                              domain,
                                              path)
    def wrap_handler(func):
        @wraps(func)
        def handle(request):
            t = request.cookie.get(name)
            tkt = None
            if t:
                tkt = SignedCookie.parse(t.value)
            request.shotauth = AuthService(tkt)
            request.header_hook(request.shotauth.header_hook())
            return func(request)
        return handle
    return wrap_handler

def shotauth_make(secretsource, valid_duration=timedelta(days=365), name='TKT', domain=None, path='/'):
    "Shared by shotauth_wrapper and shotauth (middleware"

    digest_size = hashlib.new('sha1').digest_size
    
    class SignedCookie(object):
        def signature(self):
            secret = secretsource(self.issued)
            return hmac.new(secret, self.sign_str(), hashlib.sha1).digest()

        def __str__(self):
            return "0" + base64.urlsafe_b64encode(self.issued_packed() + self.signed + self.payload)
    
        def validate(self):
            return self.signed == self.signature() and ((datetime.utcnow() - self.issued) < valid_duration)
    
        def issued_packed(self):
            return struct.pack('!L', int(time.mktime(self.issued.timetuple())))

        def sign_str(self):
            return self.issued_packed() + self.payload

        @classmethod
        def parse(cls, scookie):
            if not scookie:
                return None
            if scookie[0] == '0':
                # version 0 scookie
                data = scookie[1:]
                # a little (very little) obfuscation
                try:
                    data = base64.urlsafe_b64decode(data)
                except TypeError:
                    # no decode, no ticket
                    return None
                issued = datetime.fromtimestamp(struct.unpack('!L', data[:4])[0])
                signed = data[4:4+digest_size]
                payload = data[4+digest_size:]
                tkt = cls()
                tkt.payload = payload
                tkt.issued = issued
                tkt.signed = signed
                if tkt.validate():                
                    return tkt
            return None

        @classmethod
        def create(cls, payload):
            tkt = cls()
            tkt.payload = str(payload)
            tkt.issued = datetime.utcnow()
            tkt.signed = tkt.signature()
            return tkt

    class AuthService(object):
        def __init__(self, cookie):
            self.cookie = cookie
            self.issue_cookie = self.no_issue_cookie

        def current_payload(self):
            if self.cookie and self.cookie.validate():
                return self.cookie.payload
            else:
                return None

        def clear(self):
            self.cookie = None
            self.issue_cookie = self.issue_cookie_expire

        def _make_cookie(self):
            C = SimpleCookie()
            C[name] = str(self.cookie)
            C[name]['path'] = path
            if domain is not None:
                C[name]['domain'] = domain
            return C

        def issue_cookie_session(self, headers):
            C = self._make_cookie()
            headers.append(('Set-Cookie', C[name].OutputString()))

        def issue_cookie_persist(self, headers):
            C = self._make_cookie()
            C[name]['expires'] = (valid_duration.days * 86400) + valid_duration.seconds
            headers.append(('Set-Cookie', C[name].OutputString()))

        def issue_cookie_expire(self, headers):
            C = self._make_cookie()
            C[name] = ''
            C[name]['expires'] = -86400*2
            headers.append(('Set-Cookie', C[name].OutputString()))

        def no_issue_cookie(self, headers):
            pass

        def issue(self, username, persist=False):
            self.cookie = SignedCookie.create(username)
            if persist:
                self.issue_cookie = self.issue_cookie_persist                
            else:
                self.issue_cookie = self.issue_cookie_session

        def header_hook(self):
            def header_hook(headers):
                self.issue_cookie(headers)
            return header_hook

        def start_response_wrapper(self, func):
            def start_response(status, headers, exc_info=None):
                self.issue_cookie(headers)
                return func(status, headers, exc_info)
            return start_response

    return SignedCookie, AuthService

def shotauth(secretsource, valid_duration=timedelta(days=365), name='TKT', domain=None, path='/'):
    """Returns a WSGI middleware function which provides shotweb.authservice in the environ of requests.

    shotauth(secretsource, valid_duration=timedelta(days=365), name='TKT', domain=None, path='/')
       Secretsource should be a callable that takes one argument (a datetime instance) and returns the signing
       secret for that time.   This is used both to get the secret to sign a new authentication cookie and for
       retreiving the secret for a given time to validate the signature on an existing cookie.

       valid_duration is how long signed cookies are good for.

       name is the name of the cookie used to store the ticket.

       domain and path set the domain and path of the issued cookie.  By default the cookie domain
       is not set and the path is set to '/'.

    The object in environ['shotweb.authservice'] has a few interesting methods:

         issue(payload, persist=False) -- issue a new ticket and optionally make it a persisted cookie

         clear() -- clear the existing cookie (if any)

         current_payload() -- if the current request had a valid ticket, return the username associated with that ticket.
    """
    SignedCookie, AuthService = shotauth_make(secretsource,
                                              valid_duration,
                                              name,
                                              domain,
                                              path)
    def middleware(app):
        def auth_wrapper(environ, start_response):
            cookie = SimpleCookie(environ.get('HTTP_COOKIE'))
            t = cookie.get(name)
            tkt = None
            if t:
                tkt = SignedCookie.parse(t.value)
            service = AuthService(tkt)
            environ['shotweb.authservice'] = service
            return app(environ, service.start_response_wrapper(start_response))
        return auth_wrapper
    return middleware

def time_request(noisy=False):
    "Middleware to log (and, if noisy is on, append to text/html pages) time spent in the application."
    if type(noisy) is not bool:
        if callable(noisy):
            test = noisy
        elif isinstance(noisy, basestring):
            test = querystring_condtional(noisy)
        else:
            test = lambda e:bool(noisy)
    else:
        test = lambda e:noisy
    log = logging.getLogger('shotweb.timing')
    def log_times(environ, wall, cpu):
        path = environ.get('PATH_INFO', '??')
        log.info("Path = %s; time = %.2fms; cpu = %.2fms",
                 path, wall * 1000.0, cpu * 1000.0)
    def format_times(wall, cpu):
        return "<small>time = %.2fms; cpu = %0.2fms</small>" % (wall * 1000.0, cpu * 1000.0)
    def middleware(app):
        def noisy_wrap(environ, start_response):
            now = time.time()
            cpu = time.clock()
            type_ok = [False]
            def _start_response(status, headers, exc_info=None):
                for k, v in headers:
                    if k == 'Content-type':
                        type_ok[0] = v.startswith('text/html')
                        break
                return start_response(status, headers, exc_info)
            try:
                if test(environ):
                    result = app(environ, _start_response)                
                    if type_ok[0]:
                        spent = time.time() - now
                        cpuspent = time.clock() - cpu                    
                        return chain(result, [format_times(spent, cpuspent)])                    
                    return result
                else:
                    return app(environ, start_response)
            finally:
                spent = time.time() - now
                cpuspent = time.clock() - cpu                
                log_times(environ, spent, cpuspent)
        def quiet_wrap(environ, start_response):
            now = time.time()
            cpu = time.clock()
            try:
                return app(environ, start_response)
            finally:
                spent = time.time() - now
                cpuspent = time.clock() - cpu                
                log_times(environ, spent, cpuspent)
        if noisy:
            return noisy_wrap
        else:
            return quiet_wrap
    return middleware

def create_application(urls,
        requestType=WSGIRequest,
        unknown_handler=handle_404,
        middleware=(),
        error_handler=production_error_handler):
    "Assemble a shotweb app into a WSGI application.  same arguments as run() but doesn't run the app."
    app = make_wsgi(by2(urls), unknown_handler, requestType=requestType)
    app = capture_exceptions(app, error_handler)    
    if middleware:
        for f in middleware:
            app = f(app)
    return app

def run(urls,
        requestType=WSGIRequest,
        unknown_handler=handle_404,
        middleware=(),
        error_handler=production_error_handler, args=sys.argv):
    """Run the shotweb application

    urls is a sequence of pattern, handler. pattern can be either a
    callable that takes two arguments (path, environ) and should
    return a true result if the related handler should be used for the
    request.  handler is either a callable or should have do_METHOD
    methods for each HTTP METHOD it can handle.  If handlers is a
    callable, it may define .http_methods to tell shotweb which HTTP
    METHODS it is capable of handling.

    unknown_handler defines what happens when a request falls through
    the dispatch for the url map given.  It should be a WSGI handler
    with two arguments (environ, start_response).  The default will
    send a generic 404 error.

    middleware is a sequence of WSGI middleware to use around this
    application.

    error_handler defines the error handler to use.  It should be a
    callable of two arguments (environ, start_response).  shotweb
    defines two error_handlers: debug_error_handler uses cgitb to
    print lots of helpful traceback information and
    production_error_handler logs the exception and reports only that
    something has gone awry to the user.

    requestType allows the request class used for this application to
    be overridden.  It should extend WSGIRequest or at least implement
    the public properties and methods of WSGIRequest.
    """
    app = create_application(urls, requestType=requestType, middleware=middleware, error_handler=error_handler)
    if '-d' in args:
        # run as a daemon
        from wsgiref.simple_server import make_server
        httpd = make_server('', 1234, app)
        httpd.serve_forever()
    else:
        from flup.server.fcgi import WSGIServer
        return WSGIServer(app, multiplexed=True).run()
# this is simply not ready        
#        from shotfcgi import WSGIServer
#        return WSGIServer(app).run()


if __name__ == '__main__':
    import unittest
    class TestShotAuth(unittest.TestCase):
        def app_login(self, environ, start_response):
            self.assert_('shotweb.authservice' in environ)
            service = environ['shotweb.authservice']
            self.assert_(service.current_payload() is None)
            service.issue('Ken', persist=True)
            start_response('200 OK', [])

        def app_use(self, environ, start_response):
            self.assert_('shotweb.authservice' in environ)
            service = environ['shotweb.authservice']
            self.assert_(service.current_payload() == 'Ken')
            start_response('200 OK', [])

        def app_tampered(self, environ, start_response):
            self.assert_('shotweb.authservice' in environ)
            service = environ['shotweb.authservice']
            self.assert_(service.current_payload() is None)
            start_response('200 OK', [])

        def app_logout(self, environ, start_response):
            self.assert_('shotweb.authservice' in environ)
            service = environ['shotweb.authservice']
            self.assert_(service.current_payload() == 'Ken')
            service.clear()
            start_response('200 OK', [])

        def start_response_has_cookie(self, status, headers, exc_info=None):
            names = [x[0] for x in headers]
            vals = [x[1] for x in headers]
            self.assert_('Set-Cookie' in names)
            idx = names.index('Set-Cookie')
            self._cookie = vals[idx]                

        def start_response_no_cookie(self, statys, headers, exc_info=None):
            names = [x[0] for x in headers]
            vals = [x[1] for x in headers]
            self.assert_('Set-Cookie' not in names)

        def start_response_expire_cookie(self, statys, headers, exc_info=None):
            names = [x[0] for x in headers]
            vals = [x[1] for x in headers]
            self.assert_('Set-Cookie' in names)
            idx = names.index('Set-Cookie')
            c = SimpleCookie(vals[idx])
            self.assert_(c['TKT'].value == '')

        def testGo(self):
            save = [0]
            sekrit = lambda x:'SEKRIT'
            shotauth(sekrit)(self.app_login)({}, self.start_response_has_cookie)
            shotauth(sekrit)(self.app_use)({'HTTP_COOKIE' : self._cookie}, self.start_response_no_cookie)
            shotauth(sekrit)(self.app_use)({'HTTP_COOKIE' : self._cookie}, self.start_response_no_cookie)            
            shotauth(sekrit)(self.app_logout)({'HTTP_COOKIE' : self._cookie}, self.start_response_expire_cookie)
            tmp = list(self._cookie)
            tmp[5] = 'X'
            tmp[10] = '!'
            tmp = "".join(tmp)
            shotauth(sekrit)(self.app_tampered)({'HTTP_COOKIE' : tmp}, self.start_response_no_cookie)
            c = SimpleCookie()
            pd = struct.pack('L', 12345)
            payload = "Ken"
            signed = hmac.new('TAMPERED', pd + payload, hashlib.sha1).digest()
            c['TKT'] = pd + signed + payload
            tmp = c['TKT'].OutputString()
            shotauth(sekrit)(self.app_tampered)({'HTTP_COOKIE' : tmp}, self.start_response_no_cookie)          
            
    unittest.main()
