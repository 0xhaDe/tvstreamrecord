# coding=UTF-8
"""
    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 3 of the License,
    or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
    See the GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program; if not, see <http://www.gnu.org/licenses/>.

    @author: Pavion

"""
from __future__ import print_function
from __future__ import unicode_literals

try:
    import urllib2 as urllib32
except:
    import urllib.request as urllib32
from datetime import datetime, timedelta
import config
import time
import sys
from sql import sqlRun

def unistr(strin):
    #if type(strin) is bytes and not type(strin) is str:
    strout = u''#unicode('', "UTF-8")
    try:
        strout = strin.decode('cp1252')
    except Exception as ex: 
        pos = 0
        for pos in range(0, len(strin)-1):
            try:
                strout = strout + strin[pos:pos+1].decode('cp1252')
            except Exception as ex: 
                strout = strout + u'_'
    return strout

# converts string into time, i.e. 0x20 0x15 0x15 = 20:15:15 - what a funny way to encode time!
def str_to_delta(strin):
    try:
        h = int(hex(ord(strin[0:1])).replace("0x",""))
        n = int(hex(ord(strin[1:2])).replace("0x",""))
        s = int(hex(ord(strin[2:3])).replace("0x",""))
        return timedelta(hours=h, minutes = n, seconds = s)
    except:
        #print ("Wrong time detected")
        return timedelta(0)

# converts Modified Julian date to local date
def mjd_to_local(strin):

    try:
        MJD = ord(strin[0:1]) * 256 + ord(strin[1:2])
        Yx = int ( (MJD - 15078.2) / 365.25 )
        Mx = int ( (MJD - 14956.1 - int (Yx * 365.25) ) / 30.6001 )
        D = MJD - 14956 - int (Yx * 365.25) - int (Mx * 30.6001)
        K = 0
        if Mx == 14 or Mx == 15:
            K = 1
        Y = Yx + K + 1900
        M = Mx - 1 - K * 12

        start = datetime(Y, M, D, 0, 0, 0)

        # UTC / daytime offset
        is_dst = time.daylight and time.localtime().tm_isdst > 0
        utc_offset = - (time.altzone if is_dst else time.timezone)
        utc_off_delta = timedelta(seconds = utc_offset)

        # time offset
        t = str_to_delta(strin[2:5])

        start = start + utc_off_delta + t
    except:
        start = datetime(1900,1,1,0,0,0)

    # removing suspicious futuristic epg information
    if start > datetime.now()+timedelta(days = 60):
        start = datetime(1900,1,1,0,0,0)
    
    return start

def joinarrays(arr_max, arr_in):
    for i in arr_in:
        if not i in arr_max:
            arr_max.append(i)
    return arr_max

def read_stream(f_in):
    # Possible package sizes of MPEG-TS (default = 188)
    packagesizes = [188, 204, 208]
    size = -1

    # Sync byte (default = 'G' or 0x47)
    syncbyte = [0x47, 'G']

    # EPG data
    channel = [0x12]

    # Channel list & description
    channelinfo = [0x11]

    # Analysing stream and step size
    block_sz = 1000
    mybuffer = f_in.read(block_sz)
    for i in range(0, 400):
        if mybuffer[i] in syncbyte:
            for s in packagesizes:
                if mybuffer[i+s] in syncbyte and mybuffer[i+s*2] in syncbyte and mybuffer[i+s*3] in syncbyte:
                    size = s
                    break
            if size != -1:
                break
    if size == -1:
        print ("No sync byte found, probably not a MPEG2 stream. Aborting...")
        return

    # syncronise package size and start byte
    r = range(0,1000+size,size)
    offset = r[len(r)-1]-1000
    f_in.read(offset)

    # define block amount to be read, can cause/fix performance issues
    blocktoread = 200
    block_sz = size * blocktoread

    # Loop break if X bytes read
    blocksread = 0
    maxblocksread = 1024*1024*1024 # 1 GB
    # or if Y seconds spend
    maxduration = 60
    try:
        maxduration = int(config.cfg_grab_max_duration)
    except:
        pass
    #maxduration = 5
    maxtimespend = timedelta(seconds = maxduration)
    starttime = datetime.now()

    # Continuity counter
    ccount = [-1, -1]
    ccount_new = [-1, -1]

    # Payload storing an controlling
    payload = [b"",b""]
    myfirstpayload = [b"", b""]
    ch = 0
    maxlist = [list(),list()]
    analyse = [False, False]

    # read loop
    while True:
        mybuffer = f_in.read(block_sz)
        blocksread = blocksread + block_sz
        if not mybuffer or blocksread>maxblocksread or datetime.now() -starttime>maxtimespend:
            print ("Read finished at %d/%d MB" % (blocksread/1024/1024, maxblocksread/1024/1024))
            for ch in range(0,2):
                plist = getList(payloadSort(payload[ch], False), ch)
                maxlist[ch] = joinarrays(maxlist[ch], plist)
            break
        for i in range(0, len(mybuffer), size):
            pid1 = ord(mybuffer[i+1:i+2])
            pid2 = ord(mybuffer[i+2:i+3])
            pid3 = ord(mybuffer[i+3:i+4])
            if not (pid1 & 16 or pid1 & 8 or pid1 & 4 or pid1 & 2 or pid1 & 1) and (pid2 in channel  or pid2 in channelinfo):

                if pid2 in channel:
                    ch = 0
                elif pid2 in channelinfo:
                    ch = 1

                # Continuity control
                ccount_new[ch] = pid3 - (pid3 >> 4 << 4)
                if ccount[ch]!=-1 and not (ccount_new[ch] == ccount[ch] + 1 or (ccount_new[ch] == 0 and ccount[ch] == 15)):
                    # Out of sync!
                    payload[ch] = payloadSort(payload[ch], False)
                    analyse[ch] = True
                ccount[ch] = ccount_new[ch]
                # Continuity control ends

                tmp = mybuffer[i+4: i+size]
                # Save first payload to avoid duplicity
                if myfirstpayload[ch] == b"":
                    myfirstpayload[ch] = tmp
                elif tmp == myfirstpayload[ch]:
                    # Payload match encountered
                    # print ("Payload %s match encountered" % ch)
                    payload[ch] = payloadSort(payload[ch], True)
                    analyse[ch] = True

                # Data analyse and matching
                if analyse[ch]:
                    plist = getList(payload[ch], ch)
                    maxlist[ch] = joinarrays(maxlist[ch], plist)
                    myfirstpayload[ch] = tmp
                    payload[ch] = b""
                    analyse[ch] = False

                payload[ch] = payload[ch] + tmp

    return maxlist

# shift or cut the payloads to get the package beginning
def payloadSort(payload, match):
    pos = payload.find(b'\xff\xff\xff\xff')
    if match:
        payload = payload[pos:] + payload[:pos]
    else:
        payload = payload[pos:]
    return payload


def getList(payload, ch):
    chl = list()
    if ch == 1:
        chl = getChannelList(payload)
    else:
        chl = getGuides(payload)
    return chl

################################################################################
# Beginning with the analyse of the binary data
# Payload 0 = Guide information

def getGuides(pl):
    guides = list()

    try:
        # Sorting the tables, taking 4*, 5* and 6* tables only.
        guidetext = b""
        pos0 = -1
        pos1 = -1
        
        for i in range(0, len(pl)-4):
            if ord(pl[i:i+1]) == 0xFF and ord(pl[i+1:i+2]) == 0xFF and ord(pl[i+2:i+3]) == 0x00:
                pos1 = i + 2
                if pos0 != -1:
                    guidetext = guidetext + b"////" + pl[pos0+1:pos1]
                    pos0 = -1
                if ord(pl[i+3:i+4]) >> 4 == 4 or ord(pl[i+3:i+4]) >> 4 == 5 or ord(pl[i+3:i+4]) >> 4 == 6:
                    pos0 = i+2
        if pos0!=-1: #end of string
            guidetext = guidetext + b"////" + pl[pos0+1:]

        # Separating the tables into a list
        guidelist = guidetext.split(b"////")

        for guide in guidelist:
            if len(guide)>14:
                lenpos = 0
                slen = 0
                pos = 0
                slen = (  ord(guide[1:2])  - (ord(guide[1:2]) >> 4 << 4 ) )*256 + ord(guide[2:3])
                while True:
                    tid = (ord(guide[lenpos:lenpos+1]) >> 4)
                    if tid==5 or tid == 6:
                        pos = lenpos
                        # Channel ID
                        sid = ord(guide[pos+3:pos+4])*256 + ord(guide[pos+4:pos+5])

                        pos = pos + 14
                        while pos - lenpos < slen-10:

                            #eid = ord(guide[pos])*256 + ord(guide[pos+1]) # Event ID
                            start = mjd_to_local(guide[pos+2:pos+7])
                            duration = str_to_delta(guide[pos+7:pos+10])


                            if pos+11>=len(guide):
                                break

                            dlen = (  ord(guide[pos+10:pos+11])  - (ord(guide[pos+10:pos+11]) >> 4 << 4 ) )*256 + ord(guide[pos+11:pos+12])
                            if dlen>0:
                                pos2 = pos + 17
                                # Steuerbyte for several descriptions (?)
                                stb = guide[pos2+1:pos2+2]
                                desc = list()
                                if stb==b'\x05': # several descriptions / lines available

                                    while pos2<pos+12+dlen-1 and pos2<=len(guide):
#                                        print (pos2, guide[pos2:pos2+1])
                                        if guide[pos2:pos2+1]==b'\x4E':
                                            pos2 = pos2 + 7
                                        elif guide[pos2:pos2+1]==b'\x50' or guide[pos2:pos2+1]==b'\x54':
                                            break
                                        elif guide[pos2:pos2+1]==b'\x00' and guide[pos2+1:pos2+2]==b'\x54': # seems to be a delimiter between title and description
                                            pos2 = pos2 + 12

                                        dlen2 = ord(guide[pos2:pos2+1])

                                        if dlen2<=0 or pos2+dlen2+1>=pos+12+dlen-1: #dunno
                                            break

                                        desc.append(guide[pos2+2:pos2+1+dlen2])

                                        #desccnt = desccnt + 1
                                        pos2 = pos2+dlen2+1
                                else: # only one description available
                                    dlen2 = ord(guide[pos2:pos2+1])
                                    desc.append(guide[pos2+1:pos2+1+dlen2])

                                sumdesc = b''
                                cntdesc = 0
                                for cntdesc in range(0, len(desc)):
                                    # remove invalid entries
                                    if not (b'\x1B' in desc[cntdesc] or b'\x03' in desc[cntdesc] or b'\x04' in desc[cntdesc] or b'\x05' in desc[cntdesc] or b'\x06' in desc[cntdesc]):
                                        sumdesc = sumdesc + desc[cntdesc]
                                        if len(desc[cntdesc]) < 246 and cntdesc < len(desc) - 1:
                                            sumdesc = sumdesc + b'\n'
                                # remove empty
                                if len(sumdesc)>1:
                                    guides.append([sid, start, duration, unistr(sumdesc.replace(b'\x8a', b'\n'))])

                            pos = pos + dlen + 12
                    lenpos = lenpos + slen + 4
                    if lenpos+2>=len(guide):
                        break
                    if ord(guide[lenpos-1:lenpos]) == 0x50: # dunno
                        lenpos = lenpos - 1
                    slen = (  ord(guide[lenpos+1:lenpos+2])  - (ord(guide[lenpos+1:lenpos+2]) >> 4 << 4 ) )*256 + ord(guide[lenpos+2:lenpos+3])
                    tid = (ord(guide[lenpos:lenpos+1]) >> 4)

    except Exception as ex:
        #print ("Unexpected error with EPG grab, you may need to try again.")
        #print(ex)
        pass

    return guides

################################################################################
# Payload 1 - Channel info
# 0x42 and 0x46 tables are to be taken

def getChannelList(pl):
    channellist = list()
    try:
        splittables = pl.replace(b'\xff\x00\x46', b'\xff\x00\x42').split(b'\xff\x00\x42')
        for table in splittables:
            pos =  table.find(b'\xff\xff\xff\xff')
            if pos!=-1:
                table = table[:pos]
            # avoid duplicate headers
            header = table[0:10]
            pos = table.find(header, 10)
            if pos!=-1:
                table = table[pos:]

            pos = 10

            dlen = 0
            while pos < len(table)-4:
                cid = ord(table[pos:pos+1])*256 + ord(table[pos+1:pos+2])
                dlen = (  (ord(table[pos+3:pos+4]) >> 4 << 4 )- ord(table[pos+3:pos+4])  )*256 + ord(table[pos+4:pos+5])
                if dlen < 0:
                    break

                i = pos+6

                if table[i-1:i]==b'V' or table[i-1:i]==b'H':
                    i = i + 2
                  
                clen = ord(table[i:i+1])
                provider = table[i+1: i+clen+1].replace(b'\x86', b"").replace(b'\x87', b"").replace(b'\x05', b"")
                i = i + clen + 1
                clen = ord(table[i:i+1])

                channame = table[i+1: i+clen+1]
                channame = channame.replace(b'\x86', b"").replace(b'\x87', b"").replace(b'\x05', b"")

                if channame!=b"." and not b'\xff' in channame and not b'\xf3' in channame:
                    channellist.append([cid, provider, unistr(channame)])

                pos = pos + 5 + dlen
    except Exception as ex:
        pass

    return channellist

def savePayloads(payloads):
    for i in range(0, 2):
        f = open("out-%s.hex" % i, "wb")
        f.write(payloads[i])
        f.close()

def loadPayloads():
    payloads = [b"",b""]
    for i in range(0, 2):
        f = open("out-%s.hex" % i, "rb")
        payloads[i] = f.read()
        f.close()
    return payloads

from operator import itemgetter
def getFullList(f):
    fulllist = list()

    lists = read_stream(f)
    if not lists:
        print ("No EPG information found")
        return fulllist

    guides = lists[0]
    channellist = lists[1]

#    print ("guides %s" % (len(guides)))
#    for g in guides:
#        print (g[0], g[1], g[2], g[3].encode("UTF-8"))

#    print ("channellist %s" % (len(channellist)))
#    for g in channellist:
#        print (g[0], g[1], g[2])

    # If there is no channel list contained within the stream, try to use URLs instead
    if len(channellist)==0:
        rows=sqlRun('SELECT cname, cpath FROM channels WHERE cenabled=1')
        if rows:
            for row in rows:
                lastpart = row[1].split("/")[-1]
                if lastpart.endswith("FF"):
                    sid = int(row[1][-12:-8], 16)
                    channellist.append([sid, "SQL", row[0]])
                else:
                    spl = lastpart.split(":",7)
                    if len(spl) == 8:
                        if len(spl[3])==4:
                            sid = int(spl[3], 16)
                            channellist.append([sid, "SQL", row[0]])

        if len(channellist) > 0:
            print ("Could not extract a channel list from provided stream, tried to use URLs instead")
        else:
            print ("Could not also extract a channel list from your URLs. Please check the About page for more details")

    for l in guides:
        for c in channellist:
            if l[0] == c[0] and l[1] > datetime.now() - timedelta(hours=8):
                fulllist.append([c[2], l[1], l[2], l[3]])
                break
    fulllist = sorted(fulllist, key=itemgetter(0,1,2))

    # remove duplicates
    for i in range(len(fulllist)-1,0,-1):
        if fulllist[i][0] == fulllist[i-1][0] and fulllist[i][1] == fulllist[i-1][1] and fulllist[i][2] == fulllist[i-1][2]:
            if len(fulllist[i][3]) > len(fulllist[i-1][3]):
                fulllist[i-1][3] = fulllist[i][3]
            fulllist.pop(i)

    print ("EPG grab finished with %s channels, %s guide infos, joined amount: %s" % (len(channellist), len(guides), len(fulllist)))

    return fulllist

def startgrab(myrow):
    fulllist = list()
    try:
        print ("EPG grabbing started on %s for %s seconds" % (myrow[0], config.cfg_grab_max_duration))
        inp = urllib32.urlopen(myrow[1])
        fulllist = getFullList(inp)
        inp.close()
    except:
        print ("Supplied stream could not be found or opened, aborting...")
        pass
    return fulllist

def main(argv=None):
    fulllist = list()
    inp = None
    if argv is None:
        argv = sys.argv
    if len(argv)>1:
        try:
            if argv[1].find("://")!=-1: # URL
                print ("EPG grabbing started on %s for %s seconds" % (argv[1], config.cfg_grab_max_duration))
                inp = urllib32.urlopen(argv[1])
            else:
                inp = open(argv[1], "rb")
        except:
            print ("Supplied file/stream could not be found, aborting...")
            return fulllist
    else:
        inp = open("O:/20140511124301 - test.mpg", "rb")
        print ("Opening local file")

    fulllist = getFullList(inp)
    
    return 
    
if __name__ == "__main__":
    sys.exit(main())
