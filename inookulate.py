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

cookies = http.cookiejar.MozillaCookieJar('cookies')

def prepare_request(request):
    """Add headers to the given Request object to impersonate a NOOK device."""
    request.add_header('Referer',
            'bnereader.barnesandnoble.com')
    request.add_header('User-Agent',
            'BN ClientAPI Java/1.0.0.0 (bravo;bravo;1.5.0;P001000021)')

    cookies.add_cookie_header(request)

def authenticate(email, password):
    """Use the given username and password to authenticate to BN.

    Return boolean indicating success. If successful, authentication cookies
    are saved in the global CookieJar named cookies.
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
    prepare_request(request)

    with urllib.request.urlopen(request) as response:
        root = ElementTree.fromstring(response.read())

        status_path = "./stateData/data[@name='signedIn']"
        status = bool(int(root.find(status_path).text))

        if status:
            cookies.extract_cookies(response, request)

        return status

def log_in_with_prompt():
    """Complete a full login flow, prompting the user for credentials."""
    authenticated = False
    while not authenticated:
        email = input('Email: ')
        password = getpass.getpass('Password: ')

        authenticated = authenticate(email, password)
        if not authenticated:
            print('Login failed. Please try again')

    cookies.save(ignore_discard=True)

def get_cchash():
    """Retrieve the user's credit card hash used for EPUB encryption.

    Requires login. Returned string is the Base64-encoded hash, suitable
    for use with tools like ignobleepub.
    """
    url = 'https://cart4.barnesandnoble.com/services/service.aspx?service=1'
    post_values = [
        ('schema', '1'),
        ('outformat', '5'),
        ('Version', '2'),
        ('stage', 'deviceCreditCardHash'),
        ]

    post_data = urllib.parse.urlencode(post_values).encode()
    request = urllib.request.Request(url, post_data)
    prepare_request(request)

    with urllib.request.urlopen(request) as response:
        root = ElementTree.fromstring(response.read())

        cchash_path = './payMethod/ccHash'
        cchash = root.find(cchash_path).text

        return cchash

def get_listing():
    """Retrieve a listing of all the user's purchased books.

    Requires login. Returns a dictionary with delivery IDs as keys and book
    titles as values.
    """
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
    prepare_request(request)

    with urllib.request.urlopen(request) as response:
        root = ElementTree.fromstring(response.read())

        book_path = './SyncBody/Sync/Add/Item/Data/LockerItem'
        books = {}
        for book in root.findall(book_path):
            id = int(book.get('DeliveryId'))
            title = book.find('./ProductData/product/titles/title').text

            books[id] = title

        return books

class License:
    pass

def get_license(id):
    """Retrieve information including the EPUB URL and rights.xml of a book.

    Requires login. Returns a License object containing the string properties
    download_url, info_url, and rights_xml.
    """
    url = 'http://edelivery.barnesandnoble.com/EDS/LicenseService.svc/GetLicense2/{}/epub'
    url = url.format(id)

    request = urllib.request.Request(url)
    prepare_request(request)

    with urllib.request.urlopen(request) as response:
        root = ElementTree.fromstring(response.read())

        item_path = './Products/item'
        item = root.find(item_path)

        license = License()
        license.download_url = item.find('./eBookUrl').text
        license.info_url = item.find('./infoDocUrl').text
        license.rights_xml = item.find('./license').text

        return license

def save_file(url, id, path):
    """Download book from given URL with given ID to given path."""
    request = urllib.request.Request(url)
    request.add_header('BN-Environment', 'Backend')
    request.add_header('BN-Item-ID', str(id))
    prepare_request(request)

    with urllib.request.urlopen(request) as response, open(path, 'wb') as out:
        shutil.copyfileobj(response, out);

try:
    cookies.load(ignore_discard=True)
except OSError:
    print('Please log in to retrieve a book')
    log_in_with_prompt()

library = get_listing();

print('You own the following books:')
for id, title in sorted(library.items(), key=lambda x: x[1]):
    print('{:<11d} {}'.format(id, title))

id = int(input('ID to download: '))
license = get_license(id)

path = str(id) + '.epub'
save_file(license.download_url, id, path)

with zipfile.ZipFile(path, 'a') as epub:
    if 'META-INF/encryption.xml' in epub.namelist():
        epub.writestr('META-INF/rights.xml', license.rights_xml.encode())
        print('Added rights.xml to encrypted EPUB')
    else:
        print('EPUB is not encrypted')

#cchash = get_cchash()
