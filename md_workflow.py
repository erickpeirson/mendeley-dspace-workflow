#!/usr/bin/env python

import os
import urllib2
import webapp2
import xml.etree.ElementTree as ET

import wsgiref.handlers
from google.appengine.dist import use_library
use_library('django', '1.2')

import cgi
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext.webapp import template

import bib

#   Connect to the Mendeley API, and get all of the folders from the group

#   Given a folder, create a temporary data scheme for all of the entries in the folder

#   Update the temporary data, given form data

#   Given an entry, download PDF from Mendeley API

#   Update the temporary data with additional bitstreams, uploaded by user

#   Export temporary data as a DSpace-friendly CSV + bitsreams in a zip archive


class dspace_item:
    def __init__ (self):
        #   TODO: All of the fields...
        return None

class Corpus(db.Model):
    title = db.StringProperty(required=True)
    uri = db.StringProperty(required=True)
    size = db.IntegerProperty(required=True)

class Paper(db.Model):
#   Based on the dublin core fields used in the HPS DSpace respository
    title = db.StringProperty()
    creator = db.StringListProperty()
    creator_uri = db.StringListProperty()
    date = db.StringProperty()
    description_abstract = db.StringProperty()
    description_citation = db.StringProperty()
    source = db.StringProperty()
    source_uri = db.StringProperty()
    date_digitized = db.StringProperty()
    format_extent = db.IntegerProperty()
    type = db.StringProperty()
    language = db.StringProperty()
    relation_ispartof = db.StringProperty()
    rights = db.StringProperty()
    rights_holder = db.StringProperty()
    file_pdf = db.StringProperty()
    file_cocr = db.StringProperty()
    file_references = db.StringProperty()

    completion = db.IntegerProperty(required=True)
    checked = db.StringListProperty()

    corpus = db.StringProperty(required=True)
    
class CorporaHandler(webapp2.RequestHandler):
    def get(self):
        corpora = db.GqlQuery("SELECT * FROM Corpus")
        corpora_withID = []
        for c in corpora:
            c.id = c.key().id()
            corpora_withID.append(c)
        values = {
            'corpora': corpora_withID
        }
        self.response.out.write(template.render('corpora.html', values))

class AddCorpusHandler(webapp2.RequestHandler):
    def create_paper(self, corpus, record):
    #   Keep track of fields that are likely OK
        checked = []
    
    #   Sometimes the journal volume is missing.
        try:
            volume = record['volume']
            checked.append('description_citation')
        except KeyError:
            volume = "None"
        
    #   Try to calculate Paper.format_extent
        pages = record['page'].split('-')
        try:
            format_extent = int(pages[1]) - int(pages[0])
            checked.append('format_extent')
        except ValueError:
            format_extent = 0

    #   Create list of authors for Paper.creator
        authors = []
        authors_uri = []
        for author in record['author']:
            try:
                authors.append(author['family'].encode('ascii', 'ignore') + ", " + author['given'])
            except KeyError:
                authors.append(author['family'])
            authors_uri.append(' ')

    #   These will rarely change
        checked.append('language')
        checked.append('type')
        checked.append('relation_ispartof')
        checked.append('rights')
    
        Paper(corpus = corpus,
            title = record['title'],
            description_citation = "Citation: " + record['journal'] + " " + volume + ": " + record['page'],
            date = record['issued']['literal'],
            creator = authors,
            creator_uri = authors_uri,
            language = "eng",
            type = "text",
            relation_ispartof = "http://hdl.handle.net/10776/3984",
            rights = "Copyright material. See dc.rights.holder.",
            format_extent = format_extent,
            completion = 0,
            checked = checked).put()

    #   TODO: make this depend on successful Paper.put()
        return True
        
    def get(self):
        self.response.out.write(template.render('add_corpus.html', {}))
    
    def post(self):
    #   Make sure the user entered something
        if (self.request.get('title') == ''):
            self.response.out.write('No title given!')
            return
        if (self.request.get('uri') == ''):
            self.response.out.write('No uri given!')
            return
        if (self.request.get('bibtex') == ''):
            self.response.out.write('No BibTex file given!')
            return
            
    #   Make sure corpus doesn't already exist
        corpora = db.GqlQuery("SELECT * FROM Corpus")
        for c in corpora:
            if c.uri == self.request.get('uri'):
                self.response.out.write('Corpus already exists.')
                return
        
    #   https://github.com/ptigas/bibpy
        parser = bib.Bibparser(self.request.get('bibtex'))
        parser.parse()

    #   Add corpus to datastore
        corpus = Corpus(title=self.request.get('title'), uri=self.request.get('uri'), size=len(parser.records))
        corpus.put()
        c_key = corpus.key()

    #   Add papers to datastore
        for record in parser.records:
            self.create_paper(str(c_key), parser.records[record])

        self.redirect('/corpora')

class ViewCorpusHandler(webapp2.RequestHandler):
    def get(self, id):
        corpus = Corpus.get_by_id(int(id))
        papers = db.GqlQuery("SELECT * FROM Paper WHERE corpus = '"+str(corpus.key())+"'")
        papers_withID = []
        for paper in papers:
            paper.id = paper.key().id()
            papers_withID.append(paper)
        
        values = {
            'corpus': corpus,
            'papers': papers_withID
        }
        self.response.out.write(template.render('corpus.html', values))

class ViewPaperHandler(webapp2.RequestHandler):
    def get(self, id):
        paper = Paper.get_by_id(int(id))
        creators = []
        checked = []
        for i in range(0, len(paper.creator)):
            try:
                creators.append((i, paper.creator[i], paper.creator_uri[i]))
            except IndexError:
                creators.append((i, paper.creator[i], None))

        values = {
            'paper': paper,
            'creators': creators
        }
        self.response.out.write(template.render('paper.html', values))
        
    def post(self, id):
        paper = Paper.get_by_id(int(id))
        form = cgi.FieldStorage()
        
    #   Update checked
        checked = form.getvalue("checked")
        if checked is not None:
            paper.checked = checked
        else:
            paper.checked = []
        try:
            paper.completion = int((float(len(checked)) / float(len(form)))*100)
        except TypeError:
            pass

    #   Bulk mapping, takes tuples: (old_value, new_value)
        creator_uri_map = []    #   (creator, creator_uri)
        creator_map = []        #   (creator, creator)

    #   Check for udpated fields
        for field in form:
            value = form.getvalue(field)
            if value != '':
            #   Check for updates to creator or creator_uri
                if field.find('creator_uri') > -1:
                    cu_split = field.split('_')
                    paper.creator_uri[int(cu_split[len(cu_split)-1])] = value
                elif field.find('creator') > -1:
                    c_split = field.split('_')
                    paper.creator[int(c_split[len(c_split)-1])] = value
                else:                               #   Any other modified field should get picked up here
                    setattr(paper, field, value)
                if field is not 'checked':         
                    paper.checked.append(field)     #   If it was modified, we assume it was checked
        paper.put()
    
    #   Take us back to the working corpus
    #    corpus = Corpus.get(paper.corpus).key().id()
    #    self.redirect('/corpora/view/'+str(corpus))

class RootHandler(webapp2.RequestHandler):
    def get(self):
        self.response.out.write(template.render('md_workflow.html', {}))

class BitstreamHandler(webapp2.RequestHandler):
    def get(self, paper_id, type):
        paper = Paper.get_by_id(int(paper_id))
        
        upload_url = blobstore.create_upload_url('/upload')
        values = {
            'paper': paper,
            'type': type,
            'id': paper_id,
            'upload_url': upload_url
        }
        self.response.out.write(template.render('bitstream.html', values))

class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        upload_files = self.get_uploads('file')  # 'file' is file upload field in the form
        blob_info = upload_files[0]
        
    #   Update paper in datastore
        paper_entity = Paper.get_by_id(int(self.request.get('paper')))
        setattr(paper_entity, self.request.get('type'), str(blob_info.key()))
        paper_entity.put()
        
    #   Back to working corpus
        corpus = Corpus.get(paper_entity.corpus).key().id()
        self.redirect('/corpora/view/'+str(corpus))

class ServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, resource):
        resource = str(urllib.unquote(resource))
        blob_info = blobstore.BlobInfo.get(resource)
        self.send_blob(blob_info)

class ConceptPower:
    # Wrapper for ConceptPower API; returns an ElementTree root object
    def __init__ (self):
        self.server = "http://digitalhps-develop.asu.edu:8080/conceptpower/rest/"
    
        # Test it!
        response = urllib2.urlopen(self.server+"ConceptLookup/Bradshaw/Noun").read()
        root = ET.fromstring(response)
        if not len(root) > 0:
            print "Error! Could not connect to ConceptPower API"
            
    def search (self, query):
        response = urllib2.urlopen(self.server+"ConceptLookup/"+query+"/Noun").read()
        root = ET.fromstring(response)
        if len(root) > 0:
            return root
        return None
        
    def get (self, uri):
        response = urllib2.urlopen(self.server+"Concept?id="+uri).read()
        root = ET.fromstring(response)
        if len(root) > 0:
            return root
        return None

class ConceptSearchHandler(webapp2.RequestHandler):
    def get(self, query):
        cp = ConceptPower()
        result = cp.search(query)
        self.response.out.write(result)


def main():
    app = webapp2.WSGIApplication([
        webapp2.Route(r'/corpora', handler=CorporaHandler, name="corpora"),
        webapp2.Route(r'/corpora/add', handler=AddCorpusHandler, name="add-corpus"),
        webapp2.Route(r'/corpora/view/<id>', handler=ViewCorpusHandler, name="view-corpus"),
        webapp2.Route(r'/corpora/view/paper/<id>', handler=ViewPaperHandler, name="view-paper"),
        webapp2.Route(r'/bitstream/<paper_id>/<type>', handler=BitstreamHandler, name="bitstream"),
        webapp2.Route(r'/upload', handler=UploadHandler, name="upload"),
        webapp2.Route(r'/serve/<resource>', handler=ServeHandler, name="serve"),
        webapp2.Route(r'/concept/search/<query>', handler=ConceptSearchHandler, name="concept-search"),
        webapp2.Route(r'/', handler=RootHandler, name="root")
    ])
    wsgiref.handlers.CGIHandler().run(app)

if __name__ == "__main__":
    main()