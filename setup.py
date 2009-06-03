from setuptools import setup, find_packages
# package shotweb and shotwebui together for now
setup (
    name = "shotweb",
    version = "0.5",
    install_requires = ["wsgiref", 
                        "SimpleParse",
                        "python-cjson", 
                        "pytz"],    
    dependency_links = ["http://downloads.sourceforge.net/simpleparse/SimpleParse-2.1.0a1.tar.gz?modtime=1140297103&big_mirror=0"],
    packages = find_packages(),
    py_modules = ["shotweb"],
    author = "Ken Fox",
    author_email = "fox@xythian.com",
    description = "Yet another web app framework.  WSGI.   Controls in the spirit of ASP.NET.",     
)
