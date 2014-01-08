import jinja2
import os
import sys
import re
# import urllib
import webapp2
# import logging

# sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from wtforms import Form, TextField, BooleanField, IntegerField, validators
from datetime import datetime, timedelta
from google.appengine.ext import ndb
# from google.appengine.api import users
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers


jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))
   
    
class QueryForm(Form):
    ip = TextField('IP')
    datetime = TextField('Date')
    page = TextField('Page Visited')
    maxLogs = IntegerField('Max number of logs')
    
    
class Log(ndb.Model):
    ip = ndb.StringProperty()
    datetime = ndb.DateTimeProperty()
    page = ndb.StringProperty()

    def __str__(self):
        return self.ip + ' at ' + self.datetime.isoformat() + ' accessed ' + self.page

    @classmethod
    def parseLogs(cls, logs):
        pathsByIp = {}
        
        for log in reversed(logs):
            if pathsByIp.setdefault(log.ip, {'last':log.datetime, 'paths':[[]]})['last']  + timedelta(minutes=5) < log.datetime:
                pathsByIp[log.ip]['paths'].append([log.page])
            elif len(pathsByIp[log.ip]['paths'][-1]) == 0 or pathsByIp[log.ip]['paths'][-1][-1] != log.page :
                pathsByIp[log.ip]['paths'][-1].append(log.page)            
            pathsByIp[log.ip]['last'] = log.datetime
        
        paths = []
        
        for Ip, pathByIp in pathsByIp.items():
            # paths.append(pathByIp)
            for path in pathByIp['paths']:
                newpath = ['Enters']
                i = 1
                for page in path:
                    newpath.append(str(i)+'-'+page)
                    i += 1
                newpath.append('Exits')
                paths.append(newpath)
                
        nodes = []
        links = {}
        
        for path in paths:
            link = []
            for page in path:
                if page not in nodes:
                    nodes.append(page)
            for current, next in zip(path, path[1:]):
                source = nodes.index(current)
                target = nodes.index(next)
                links.setdefault(source, {}).setdefault(target, {'value':0})['value'] += 1
                
        return [nodes, links]
    

class MainPage(webapp2.RequestHandler):
    def get(self):      
        ndblogs = Log.query().order(-Log.datetime).fetch(50)
        upload_url = blobstore.create_upload_url('/upload')
        form = QueryForm()
        
        template_values = {
            'upload_url': upload_url,
            'form': form,
            'logs': ndblogs       
        }

        template = jinja_environment.get_template('index.html')
        self.response.out.write(template.render(template_values))
        
    def post(self):
        
        ndblogs = Log.query()
        form = QueryForm(self.request.POST)

        if form.ip.data:
            ndblogs = ndblogs.filter(Log.ip == form.ip.data)
        if form.datetime.data:
            match = re.match(r"(?P<datetime1>[\d-]+\s[\d:.]+) to (?P<datetime2>[\d-]+\s[\d:.]+)$", form.datetime.data)
            if match:
                groups = match.groupdict()
                ndblogs = ndblogs.filter(Log.datetime >= datetime.strptime(groups['datetime1'], '%Y-%m-%d %H:%M:%S.%f'),
                                                Log.datetime <= datetime.strptime(groups['datetime2'], '%Y-%m-%d %H:%M:%S.%f'))
            else:
                match = re.match(r"(?P<datetime>[\d-]+\s[\d:.]+)$", form.datetime.data)
                if match:
                    groups = match.groupdict()
                    ndblogs = ndblogs.filter(Log.datetime == datetime.strptime(groups['datetime'], '%Y-%m-%d %H:%M:%S.%f'))
            
        if form.page.data:
            ndblogs = ndblogs.filter(Log.page == form.page.data)

        if form.maxLogs.data:
            ndblogs =  ndblogs.order(-Log.datetime).fetch(form.maxLogs.data)
        else:
            ndblogs =  ndblogs.order(-Log.datetime).fetch(50)
            
        upload_url = blobstore.create_upload_url('/upload')
        
        nodes, links = Log.parseLogs(ndblogs)
        
        template_values = {
            'upload_url': upload_url,
            'form': form,
            'logs': ndblogs,
            'nodes': nodes,
            'links': links
        }

        template = jinja_environment.get_template('index.html')
        self.response.out.write(template.render(template_values))        
        
        
class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    @ndb.toplevel
    def post(self):
        upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
        if len(upload_files) == 1:
            blob_info = upload_files[0]
            blob_reader = blobstore.BlobReader(blob_info)
            
            pattern = re.compile(r"""
                (?P<datetime>[\d-]+\s[\d:,]+)\s          # gets the datetime
                \[INFO\]\s root:\s                             # eats the info and root
                \[(?P<ip>[\d.]+)\]\s                          # gets the ip
                (?P<page>[\w]+)                             # gets the page       
                """, re.VERBOSE)       
            
            for line in blob_reader:
                match = pattern.match(line)
                if match: 
                    groups = match.groupdict()
                    dt = datetime.strptime(groups['datetime'], '%Y-%m-%d %H:%M:%S,%f')
                    log = Log(ip = groups['ip'], datetime = dt, page = groups['page'])
                    log.put_async()
                    
            blob_info.delete()
            
        self.redirect('/')

        
app = webapp2.WSGIApplication(
                            [('/', MainPage),
                             ('/upload', UploadHandler)
                            ], debug=True)