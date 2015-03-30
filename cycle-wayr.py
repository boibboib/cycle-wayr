#!/usr/bin/python
import praw
import requests
import re
import sys
import time
import datetime
import subprocess
import platform
import os.path
import random
import json
from apiclient.discovery import build

BOOKSTRIPNAME       = "books-covers.jpg"
BLURB_TAG           = "#####"
BANNER_TAG          = "####"
IMAGEPOOL           = "wayr"

logBuf = ""
logTimeStamp = ""
fakeit = False
confData={}


#################################################
def DEBUG(s, start=False, stop=False):

    global logBuf
    global logTimeStamp

    print (s)

    logBuf = logBuf + s + "\n\n"
    if stop:
        r.submit("bookbotlog", logTimeStamp, text=logBuf)
        logBuf = ""

#################################################


def init (useragent):
    r = praw.Reddit(user_agent=useragent)
    # so that reddit wont translate '>' into '&gt;'
    r.config.decode_html_entities = True
    return r
#################################################


def login (r, username, password):
    Trying = True
    while Trying:
        try:
            r.login(username, password)
            print('Successfully logged in')
            Trying = False
        except praw.errors.InvalidUserPass:
            print('Wrong Username or Password')
            quit()
        except Exception as e:
            print("%s" % e)
            time.sleep(5)
#################################################

def getBotConfig(r, sub):

    botConfig = {}

    wp = r.get_wiki_page(sub, "bot-config")

    lines = wp.content_md.split("\n")

    lines = [x.strip() for x in lines]

    for x in lines:
        m=re.search("(^.*?):(.*)", x)
        if m and len(m.groups()) == 2:
            botConfig[m.group(1)] =  int(m.group(2))
            print ("%s %d" % (m.group(1), botConfig[m.group(1)]))

    return botConfig

def saveBotConfig (r, sub, botConfig):

    sr = r.get_subreddit(sub)

    newWp = ""
    for x in botConfig:
        newWp += "%s: %d\n\n" % (x, botConfig[x])
        print("newWp:", newWp)

    sr.edit_wiki_page("bot-config", newWp)



def shortener(url):

    try:
        service = build("urlshortener", "v1", developerKey=confData['googlekey'])
        body = {"longUrl": url}
        resp = service.url().insert(body=body,userIp=confData['ipaddr']).execute()
    except Exception as e:
        DEBUG('Exception in shortener() trying to short(%s): %s ' % (url, e))
        return url

    if resp['id']:
        print ("shortener(): %s" % resp['id'])
        return resp['id']
    else:
        DEBUG("shortener(): %s failed" % url)
        return ''


def getShortUrls (bList):

    for i in bList:
        i['shorturl'] = shortener(i['blurb'])
        if not i['shorturl']:
            return False

    return True


def decodeBook(str):
    """ Takes a string and decodes the book format fields and returns a dict. """
    book = {"author":"", "moderator":"", "imageurl": "", "blurb": "", "title":"", "imagename":""}

    formatstrs = ['author', 'moderator', 'imageurl', 'blurb']

    # 'imagefile' is a requirement, dont proceed if it's not there
    if re.search('{imageurl}', str, re.I):
        bookarray = str.splitlines()

        # '{book}' was stripped out in .split({book}), it's always the 1st line
        book['title'] = bookarray[0]
        if len(book['title']) == 0 or len(book['title']) > 150:
            DEBUG("decodeBook: decode error - title too long or too short" + book['title'])
        else:
            for x in bookarray:

                # ensure there are alpha chars in this string
                if re.search('[a-zA-Z]', x):
                    for s in formatstrs:
                        searchstr = "{%s}(.*)" % s
                        m = re.search(searchstr, x, re.I)
                        if m:
                            book[s] = m.group(1).strip()
                            break

    if not book['title'] or not book['imageurl']:
        DEBUG("decodeBook: missing title (%s) or imageurl (%s)" % (book['title'], book['imageurl']))
        book = {}
#    print (book)
    return book



def updateBookImageName (sr, imagefile, justSave=False):
    """ update the stylesheet with the image file name.
        even if the imagename is already what we want, we still
        call set_stylesheet() because reddit requires that when
        uploading an image with the same name.
     """

    global fakeit

    sheet = sr.get_stylesheet()['stylesheet']
    newsheet = sheet
    if justSave and not fakeit:
        sr.set_stylesheet(newsheet)
        return

    if imagefile.endswith(".png") or imagefile.endswith(".jpg"):
        imagefile = imagefile[:-4]

    m = re.search("(\.titlebox\s*.*?background:\s*url\(%%.*?%%\).*?})", sheet, re.I|re.DOTALL)

    if m:
        newside = re.sub(r'background:\s*url\(%%.*%%\)', r'background: url(%%' + imagefile + r'%%)', m.group(1))

        if newside == m.group(1):
            DEBUG("updateBookImage: imagename has not changed")
        else:
            DEBUG("updateBookImage: imagename HAS changed")
            newsheet = sheet.replace(m.group(1), newside)

            # a little sanity check - newsheet should be about the same size as sheet
            if abs(len(sheet)-len(newsheet)) > 20:
                DEBUG("updateBookImage: size diff (%s) of sheet-newsheet is too much" % abs(sheet-newsheet), stop=True)
                # todo - write sheet and newsheet to file
                quit()

        if not fakeit:
            e = sr.set_stylesheet(newsheet)
            if e['errors']:
                DEBUG("updateBookImageName: error from set_stylesheet() (%s)" % e['errors'], stop=True)
                quit()
#################################################



def updateAmaClickThru(sr, blurb, banner):
    """ update the book blurb on the sidebar page """

    global fakeit

    if not blurb:
        blurb = ' '

    if not banner:
        banner = ''

    DEBUG("updateAmaClickThru: blurb (%s)" % blurb)
    DEBUG("updateAmaClickThru: banner (%s)" % banner)

    sb = sr.get_settings()["description"]
    m = re.search(BLURB_TAG + "(.*)", sb)
    if not m:
        DEBUG("updateAmaClickThru: Error finding (%s) in sidebar" % BLURB_TAG, stop=True)
        quit()

    if len(m.group(1)) < 2 and len(blurb) < 2:
        DEBUG("updateAmaClickThru: No blurb in old or new.  Not updating.");
    else:
        blurb = '[](' + blurb + ')'
        newblurb = BLURB_TAG + blurb
        newsb = re.sub(BLURB_TAG + '(.*)', newblurb, sb)


        # update banner
        m = re.search(BANNER_TAG + "([^#].*)", newsb)
        if not m:
            DEBUG("updateAmaClickThru: Error finding (%s) in sidebar" % BANNER_TAG)
        elif len(m.group(1)) < 2 or len(banner) < 5:
            DEBUG("updateAmaClickThru: No banner in old or new.  Not updating.");
        else:
            newbanner = BANNER_TAG + banner
            newsb = re.sub(BANNER_TAG + '(.*)', newbanner, newsb, count=1)

            if not fakeit:
                e = sr.update_settings(description = newsb)
                if e['errors']:
                    DEBUG("updateAmaClickThru: error from update_settings() (%s) " % e['errors'], stop=True)
                    quit()


#################################################

def updateBookStripClickThru(sr, bList, firstBook):

    global fakeit


    sb = sr.get_settings()["description"]
    m = re.search("(\* \[bsct\]\(.*?\n\n)", sb, re.I|re.DOTALL)
    if not m:
        DEBUG("updateAmaClickThru: Error finding [bsct] in sidebar", stop=True)
        quit()

    if len(m.group(1)) < 2 and len(blurb) < 2:
        DEBUG("updateAmaClickThru: No blurb in old or new.  Not updating.");
    else:
        newClickThrus = ""
        bsct = "bsct"
        for i in bList:
            newClickThrus += "* [%s](%s)\n" % (bsct, i['shorturl'])
            bsct = ""


        newClickThrus += "\n"

        it = sb.replace(m.group(1), newClickThrus)

        if not fakeit:
            e = sr.update_settings(description = it)
            if e['errors']:
                DEBUG("updateAmaClickThru: error from update_settings() (%s) " % e['errors'], stop=True)
                quit()




def downloadImage(imageUrl, localFileName, doImageConvert):

### montage -background "transparent" -geometry 103x160 -size 412x480 1.png 2.png 3.jpg 4.jpg 5.png 6.png 7.png 8.png 9.png 0.png bb.jpg
### montage -geometry 103x160 -tile 15x1 -background "transparent"  -size 412x480 1.png 2.png 3.jpg 4.jpg 5.png 6.png 7.png 8.png 9.png 0.png 10.png 11.jpg 12.png 13.png 14.png bb.jpg

    DEBUG("downloadImage: Looking for %s" % imageUrl)
    IDENTIFY = 'identify'
    CONVERT = 'convert'

    if platform.system() == 'Windows':
        IDENTIFY = 'C:/Program Files/ImageMagick-6.8.9-Q16/identify.exe'
        CONVERT = 'C:/Program Files/ImageMagick-6.8.9-Q16/convert.exe'


    ext = os.path.splitext(imageUrl)[1][1:].strip()
    if not ext:
        imageUrl = imageUrl + ".png"

    response = requests.get(imageUrl)

    if response.status_code == 200:
        print('Downloading %s...' % (localFileName))

        with open(localFileName, 'wb') as fo:
            for chunk in response.iter_content(4096):
                fo.write(chunk)

        response.connection.close()
        try:
            output = subprocess.check_output([IDENTIFY, localFileName])
            if doImageConvert:
                a = output.split()
                DEBUG("downloadImage: image is (%s) (%s)" % (a[1].decode("utf-8"), a[2].decode("utf-8")))
                if a[2] != b"163x260":
                    o = subprocess.check_output([CONVERT,  localFileName, "-resize", "163x260!", localFileName])
                    DEBUG("(%s) image converted to 163x260" % imageUrl)
                elif a[1] != b"PNG":
                    o = subprocess.check_output(["convert",  localFileName, localFileName])
                    DEBUG("(%s) image converted to PNG" % imageUrl)
        except Exception as e:
            DEBUG('downloadImage: Error in IDENTIFY or CONVERT %s' % e)
            return False

        return True
    else:
        DEBUG("downloadImage: Error(%s) finding (%s)" % (response.status_code, imageUrl))
        response.connection.close()
        return False


#################################################

def createBookStrip (bList, firstBook, outputName):

    ### montage -geometry 103x160 -tile 15x1 -background "transparent"  -size 412x480 1.png 2.png 3.jpg 4.jpg 5.png 6.png 7.png 8.png 9.png 0.png 10.png 11.jpg 12.png 13.png 14.png bb.jpg

    MONTAGE = 'montage'
    imageList = ""


    for i in bList:
        imageList += i['imagename'] + " "

    MONTAGE_CMD = " -geometry 103x160! -tile 15x1 -background \"transparent\"  -size 412x480 " + imageList + outputName
    DEBUG("createBookStrip(): " + MONTAGE_CMD)

    if platform.system() == 'Windows':
        MONTAGE = 'C:/Program Files/ImageMagick-6.8.9-Q16/montage.exe'

    try:
        output = subprocess.call(MONTAGE + MONTAGE_CMD, shell=True)
        if output:
            DEBUG('createBookStrip(): Error in MONTAGE')
            return False
    except Exception as e:
        DEBUG('createBookStrip(): Error in MONTAGE %s' % e)
        return False

    DEBUG('createBookStrip(): Success!')
    return True


#################################################

def uploadImage (sr, filename):
    """   """
    global fakeit

    if not fakeit:
        DEBUG("uploadImage: (%s)" % filename)
        sr.upload_image(filename)

    return






###############################################################################
def cycleBooks (r):

    nextBook = 0
    #
    # get the "wayr" wiki page
    #
    sr = r.get_subreddit(confData['subreddit'])
    mrp = sr.get_wiki_page(IMAGEPOOL)


    #try:
    #    f = open(CURRENT_BOOK_FILE, "r")
    #    nextBook = int(f.readline())
    #    f.close()
    #except:
    #    nextBook = 0

    try:
        botConfig = getBotConfig(r, confData['subreddit'])
        nextBook = botConfig["WAYRIndex"]
    except:
        nextBook = 0

    firstBook = nextBook

    DEBUG("cycleBooks: next book index = %d" % nextBook)

    #
    # get the list of wayr books
    #
    mrps = mrp.content_md.split("{Book}")
    bookList = []
    for i in mrps:
        i = i.strip()

        if len(i) < 10:
            continue

        myBook = decodeBook(i)
        if myBook:
            bookList.append(myBook)


    numBooks = len(bookList)
    DEBUG("found %s books" % numBooks)
    if len(bookList) < 2:
        DEBUG("Not enough books", stop=True)
        quit()

    # if we're at the end, start over from top
    if nextBook >= numBooks:
        nextBook = 0;

    DEBUG("\nfound current book **%s** at index:%s out of %s" % (bookList[nextBook]['title'], nextBook, numBooks))

    #
    # verify image file URL is valid
    #
    count = len(bookList)
    ok = False
    bookCnt = 0
    workingList = []
    while bookCnt < 15 and count > 0:
        ok = downloadImage(bookList[nextBook]['imageurl'], "%s" % (str(bookCnt) + ".png"), False)
        if ok:
            bookList[nextBook]['imagename'] = "%s" % (str(bookCnt) + ".png")
            workingList.append(bookList[nextBook])

        bookCnt += 1
        nextBook += 1
        count -= 1
        if nextBook >= numBooks:
            nextBook = 0;


    if count == 0:
        DEBUG("ERROR: Found %d IMAGES" % bookCnt, stop=True)
        quit

    #
    # create the book "strip" from the downloaded images
    #
    if not createBookStrip(workingList, firstBook, BOOKSTRIPNAME):
        DEBUG("createBookStrip() error", stop=True)
        quit()

    #
    # get the short urls before uploading image - if a shorten fails, dont proceed
    #
    DEBUG("Getting short urls...")
    if not getShortUrls(workingList):
        DEBUG("getShortUrls() error", stop=True)
        quit()

    #
    # upload the image to the stylesheet page
    #
    uploadImage(sr, BOOKSTRIPNAME)

    #
    # update stylesheet with imagefile name
    #
    updateBookImageName(sr, "", justSave=True)

    #
    # update book strip click urls
    #
    updateBookStripClickThru(sr, workingList, firstBook)


    #
    # save the current book index
    #
    indexToSave = firstBook + 7
    if indexToSave >= len(bookList):
        indexToSave = indexToSave - len(bookList)

    botConfig["WAYRIndex"] = indexToSave
    saveBotConfig (r, confData['subreddit'], botConfig)
#########################################################################


if __name__=='__main__':
    #
    # init and log into reddit
    #


    if len(sys.argv) > 1:
        if sys.argv[1] == "fakeit":
            fakeit = True
        else:
            print ("\n\n cycle-wayr <fakeit>")
            quit()

    f = open('cycle-wayr.conf', 'r')
    buf = f.readlines()
    f.close()


    for b in buf:
        if b[0] == '#' or len(b) < 5 or ":" not in b:
            continue
        confData[b[:b.find(":")]] = b[b.find(":")+1:].strip()


    if not confData['username'] or not confData['password'] or \
        not confData['subreddit'] or not confData['ipaddr'] or not confData['googlekey']:
        DEBUG('cmd: Missing username, password or subreddit')
        quit()

    r = init("cycle-wayr 1.0  /u/"+confData['username'])
    login(r, confData['username'], confData['password'])

    #confData['subreddit']="boibtest1"

    if platform.system() == 'Windows':
        formatstr = "%d%b%Y-%H:%M:%S"
    else:
        formatstr = "%d%b%Y-%H:%M:%S %Z"

    logTimeStamp = "CMR - /r/" + confData['subreddit'] + " - " + time.strftime(formatstr) + (" TrialRun" if fakeit else "")

    try:
        cycleBooks(r)

    except Exception as e:
        DEBUG('An error has occured in main(): %s' % e)
        #quit()

    DEBUG("", stop=True)





