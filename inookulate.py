#!/usr/bin/env python3

# inookulate.py
"""Save your NOOK books from the disease that is Barnes & Noble's cloud."""

import urllib.request
import urllib.parse
import http.cookiejar
from xml.etree import ElementTree
import zipfile
import shutil
import getpass

class NotAuthenticatedError(Exception):
    pass

class License:
    pass

class AuthenticationToken:
    def __init__(self, filename='cookies'):
        self.authenticated = False
        self.cookies = http.cookiejar.MozillaCookieJar(filename)
        self.load()

    def authenticate(self, email, password):
        """Use the given username and password to authenticate with BN.

        Returns boolean indicating success. If successful, the authentication
        token is updated with the new data.
        """
        url = 'https://cart2.barnesandnoble.com/services/service.asp?service=1'
        post_values = [
            ('emailAddress', email),
            ('UIAction', 'signIn'),
            ('acctPassword', password),
            ('stage', 'signIn'),
            ]

        post_data = urllib.parse.urlencode(post_values).encode()
        request = urllib.request.Request(url, post_data)
        prepare_request(request, self)

        with urllib.request.urlopen(request) as response:
            root = ElementTree.fromstring(response.read())

            status_path = "./stateData/data[@name='signedIn']"
            status = bool(int(root.find(status_path).text))

            if status:
                self.authenticated = True
                self.cookies.extract_cookies(response, request)
                self.save()

            return status

    def update_state(self):
        """Check to see if the token is authenticated.

        Updates the authenticated boolean accordingly. As a user of the class,
        you should not need to call this. It will automatically be called as
        needed to keep the authenticated variable up-to-date.
        """
        url = 'https://cart2.barnesandnoble.com/services/service.asp?service=1'
        post_values = [
            ('stage', 'signIn'),
            ]

        post_data = urllib.parse.urlencode(post_values).encode()
        request = urllib.request.Request(url, post_data)
        prepare_request(request, self)

        with urllib.request.urlopen(request) as response:
            root = ElementTree.fromstring(response.read())

            status_path = "./stateData/data[@name='signedIn']"
            status = bool(int(root.find(status_path).text))

            self.authenticated = status
            return status

    def save(self, filename=None):
        """Save the authentication token to a file.

        Uses the filename passed to the constructor if no filename is given.
        """
        self.cookies.save(ignore_discard=True, filename=filename)

    def load(self, filename=None):
        """Load an authentication token from the given file.

        Uses the filename passed to the constructor if no filename is given.
        Returns a boolean indicating whether or not a valid token was loaded.
        """
        try:
            self.cookies.load(ignore_discard=True, filename=filename)
            self.update_state()
        except OSError:
            pass

        return self.authenticated

def prepare_request(request, token=None):
    """Add headers to the given Request object to impersonate a NOOK device."""
    request.add_header('Referer',
            'bnereader.barnesandnoble.com')
    request.add_header('User-Agent',
            'BN ClientAPI Java/1.0.0.0 (bravo;bravo;1.5.0;P001000021)')

    if token is not None:
        token.cookies.add_cookie_header(request)

def log_in_with_prompt(token):
    """Complete a full login flow, prompting the user for credentials.

    Will either update the given token to an authenticated state or throw an
    exception.
    """
    while not token.authenticated:
        email = input('Email: ')
        password = getpass.getpass('Password: ')

        if not token.authenticate(email, password):
            print('Login failed. Please try again')

def get_cchash(token):
    """Retrieve the user's credit card hash used for EPUB encryption.

    Requires login. Returned string is the Base64-encoded hash, suitable
    for use with tools like ignobleepub.
    """
    if not token.authenticated:
        raise NotAuthenticatedError

    url = 'https://cart4.barnesandnoble.com/services/service.aspx?service=1'
    post_values = [
        ('schema', '1'),
        ('outformat', '5'),
        ('Version', '2'),
        ('stage', 'deviceCreditCardHash'),
        ]

    post_data = urllib.parse.urlencode(post_values).encode()
    request = urllib.request.Request(url, post_data)
    prepare_request(request, token)

    with urllib.request.urlopen(request) as response:
        root = ElementTree.fromstring(response.read())

        cchash_path = './payMethod/ccHash'
        cchash = root.find(cchash_path).text

        return cchash

def get_library(token):
    """Retrieve a listing of all the user's purchased books.

    Requires login. Returns a dictionary with delivery IDs as keys and book
    titles as values.
    """
    if not token.authenticated:
        raise NotAuthenticatedError

    url = 'http://sync.barnesandnoble.com/sync/001/Default.aspx'
    post_data = """<?xml version="1.0" encoding="utf-8"?>
<SyncML>
  <SyncHdr>
    <VerDTD>1.1</VerDTD>
    <VerProto>SyncML/1.1</VerProto>
    <SessionID>1</SessionID>
    <Source>
      <LocURI>0</LocURI>
    </Source>
    <Target>
      <LocURI>http://sync.barnesandnoble.com/sync/001/Default.aspx</LocURI>
    </Target>
  </SyncHdr>
  <SyncBody>
    <Alert>
      <Data>201</Data>
      <Item>
        <Target>
          <LocURI>uri://com.bn.sync/store/digital_locker</LocURI>
        </Target>
        <Source>
          <LocURI>0/products</LocURI>
        </Source>
        <Meta>
          <Anchor>
            <Last/>
          </Anchor>
        </Meta>
      </Item>
    </Alert>
    <Final/>
  </SyncBody>
</SyncML>
""".encode()

    request = urllib.request.Request(url, post_data)
    request.add_header('Content-Type', 'application/vnd.syncml+xml')
    prepare_request(request, token)

    with urllib.request.urlopen(request) as response:
        root = ElementTree.fromstring(response.read())

        book_path = './SyncBody/Sync/Add/Item/Data/LockerItem'
        books = {}
        for book in root.findall(book_path):
            id = int(book.get('DeliveryId'))
            title = book.find('./ProductData/product/titles/title').text

            books[id] = title

        return books

def get_license(token, id):
    """Retrieve information including the EPUB URL and rights.xml of a book.

    Requires login. Returns a License object containing the string properties
    download_url, info_url, and rights_xml.
    """
    if not token.authenticated:
        raise NotAuthenticatedError

    url = 'http://edelivery.barnesandnoble.com/EDS/LicenseService.svc/GetLicense2/{}/epub'
    url = url.format(id)

    request = urllib.request.Request(url)
    prepare_request(request, token)

    with urllib.request.urlopen(request) as response:
        root = ElementTree.fromstring(response.read())

        item_path = './Products/item'
        item = root.find(item_path)

        license = License()
        license.download_url = item.find('./eBookUrl').text
        license.info_url = item.find('./infoDocUrl').text
        license.rights_xml = item.find('./license').text

        return license

def save_file(token, url, id, path):
    """Download book from given URL with given ID to given path.

    Requires login.
    """
    if not token.authenticated:
        raise NotAuthenticatedError

    request = urllib.request.Request(url)
    request.add_header('BN-Environment', 'Backend')
    request.add_header('BN-Item-ID', str(id))
    prepare_request(request, token)

    with urllib.request.urlopen(request) as response, open(path, 'wb') as out:
        shutil.copyfileobj(response, out);


token = AuthenticationToken('cookies')
if not token.authenticated:
    print('Please log in to retrieve a book')
    log_in_with_prompt(token)

print('Fetching library...')
library = get_library(token);

print('You own the following books:')
for id, title in sorted(library.items(), key=lambda x: x[1].lower()):
    print('{:<11d} {}'.format(id, title))

id = int(input('ID to download: '))
license = get_license(token, id)

path = str(id) + '.epub'
print('Saving {} as {}...'.format(license.download_url, path))
save_file(token, license.download_url, id, path)

with zipfile.ZipFile(path, 'a') as epub:
    if 'META-INF/encryption.xml' in epub.namelist():
        epub.writestr('META-INF/rights.xml', license.rights_xml.encode())
        print('Added rights.xml to encrypted EPUB')
    else:
        print('EPUB is not encrypted')

#cchash = get_cchash()
