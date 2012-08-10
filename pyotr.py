import bencode
import requests
import sha
import struct
import socket
import Queue
import threading
import time

''' Metainfo '''

def decode(file_load):
    ''' Decodes the bencoded file, returns decoded dictionary '''
    torrent = bencode.bdecode(open(file_load, 'rb').read())
    return torrent


def splice_shas(torrent):
    ''' Splices the SHA1 keys into a list '''
    print metainfo['info'].keys()
    print metainfo['info']['piece length']
    pieces = metainfo['info']['pieces']
    sha_list = []

    for i in range(len(pieces)/20):
       sha_list.append(pieces[20*i:20*(i+1)])
    return sha_list


def getdicthash(file_load):
    ''' Returns the SHA1 hash of the 'info' key in the metainfo file '''
    contents = open(file_load, 'rb').read()
    start = contents.index('4:info') + 6
    end = -1
    dictliteral = contents[start:end]
    dictsha = sha.new(dictliteral)
    return dictsha.digest()



''' Networking? '''


def recvall(socket, expected):
    ''' Allows you to receive an expected amount off a socket '''
    data = ''
    while True:
        newdata = socket.recv(expected)
        data += newdata
        expected = expected - len(newdata)
        if expected == 0:
            break
    return data


''' Tracker '''


def announce(file_load):
    ''' Announces to a tracker 
    
    Currently returns 1 peer's IP and port, hardcoded '''
    torrent = decode(file_load)
    left = len(sha_list)
    payload = {'info_hash': info_hash,
               'peer_id':'-PYOTR0-dfhmjb0skee6',
               'port':'6881',
               'uploaded':'0',
               'downloaded':'0',
               'key':'2c4dec5f',
               'left': left,
               'no_peer_id':'0',
               'event':'started',
               'compact':'1',
               'numwant':'30'}

    response = requests.get(torrent['announce'], params = payload)
    reply = bencode.bdecode(response.content)
    print 'peers: ' + repr(reply['peers'])
    print 'complete: ' + str(reply['complete'])
    print 'interval: ' + str(reply['interval'])
    print 'incomplete: ' + str(reply['incomplete'])
    
    data = reply['peers']
    multiple = len(data)/6
    print struct.unpack("!" + "LH"*multiple, data)
    for i in range(0, multiple):
        print socket.inet_ntop(socket.AF_INET, data[6*i:6*i+4]) + ":" + repr(struct.unpack("!H", data[6*i+4:6*i+6])[0])
    ip =  socket.inet_ntop(socket.AF_INET, data[0:4])
    port = int(repr(struct.unpack("!H", data[4:6])[0]))
    return (ip, port)











''' Peer '''

def handshake(socket):
    ''' Initiates handshake with peer '''
    info_hash = getdicthash('Sapolsky.mp4.torrent')    
    msg = chr(19) + 'BitTorrent protocol' + '\x00'*8 + info_hash + '-PYOTR0-dfhmjb0skee6'
    socket.send(msg)
    print "Handshake sent: ", repr(msg)
    print "Handshake rcvd: %s" % repr(socket.recv(4096))


def make_have(piece):
    ''' Constructs msg for sending a 'have piece' msg to a peer '''
    return struct.pack('!L', 5) + chr(4) + struct.pack('!L', piece)


def make_request(piece, offset, length):
    ''' Constructs msg for requesting a block from a peer '''
    return struct.pack('!L', 13) + chr(6) + struct.pack('!LLL', piece, offset, length)

def flagmsg(socket):
    ''' Takes a bit off socket buffer; returns a tuple of the action and the data from a socket

    BLOCKS'''
    first  = socket.recv(4)
    length = struct.unpack('!L', first)[0]
    id_data = recvall(socket, length)
    if id_data == '':
        return
    id = id_data[0]
    data = id_data[1:]
    if id == '\x00':
        return ('choke', None)
    elif id == '\x01':
        return ('unchoke', None)
    elif id == '\x02':
        return ('interested', None)
    elif id == '\x03':
        return ('not interested', None)
    elif id == '\x04':
        return ('have', data)
    elif id == '\x05':
        return ('bitfield', data)
    elif id == '\x06':
        return ('request', data)
    elif id == '\x07':
        return ('piece', data)
    elif id == '\x08':
        return ('cancel', data)


def receive_loop(index, socket):
    ''' Currently hardcodes for first data block '''
    if piece_queue.empty():
        piece_data = [None]*(file_size%piecelength)
    else: piece_data = [None]*piece_length
    last_req_length = 16384
    while True:
        flag, data = flagmsg(socket)
        print flag
        if flag == 'bitfield':
            num = int(data.encode('hex'), 16)
            bitfield = bin(num)[2:len(sha_list)+2]
            bfield = [ (True if x == '1' else False) for x in bitfield ]
            print bitfield
            print bfield[0:10]
            time.sleep(2)
            print "... as you can see, it's a seeder!"
            time.sleep(5)
        elif flag == 'unchoke':
            ''' If unchoked, send a request! '''
            print 'unchoked!'
            socket.sendall(make_request(index, 0, 16384))
            last_req_length = 16384
            # we don't actually need this, can get from length of data. attribute it?
        elif flag == 'piece':
            piece, offset = struct.unpack('!LL', data[:8])
            print repr(data[:20])
            print "Piece Index: ", piece 
            print "Offset:", offset
            print "Length sent:",len(data[8:])
            piece_data[offset:offset+last_req_length] = data[8:]
            if None not in piece_data:
                print "yay! finished a piece!"
                break
            first_blank = piece_data.index(None)
            size_left = piece_data.count(None)
            socket.sendall(make_request(index, first_blank, min(16384, size_left)))
            last_req_length = min(16384, size_left)
    return piece_data



''' CLASS STUFF '''

class PeerConnection(threading.Thread):
    ''' Grab blocks from peers, pulling indices off queue '''
    def __init__(self, piece_queue, ip, port):
        threading.Thread.__init__(self)
        self.piece_queue = piece_queue
        self.port = port
        self.ip = ip
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.connect((self.ip, self.port))
        handshake(self.s)
    
    def run(self):
        while not piece_queue.empty():
            index, now_sha = self.piece_queue.get()
            self.s.sendall(make_request(index, 0, 16384))
            current_piece = receive_loop(index, self.s)
            current_piece = "".join(current_piece)
            piece_sha = sha.new(current_piece).digest()
            if now_sha == piece_sha:
                print "SHA1 matches for piece", index
                self.s.sendall(make_have(index))
                self.piece_queue.task_done()
            else: print "FAILED CHECKSUM :("


''' MAIN '''
file_load = 'Sapolsky.mp4.torrent'

piece_queue = Queue.Queue()
metainfo = decode(file_load)
file_size = metainfo['info']['length']
info_hash = getdicthash(file_load)
piece_length = metainfo['info']['piece length']

sha_list = splice_shas(file_load)
piece_list = zip([x for x in range(len(sha_list))], sha_list)
for piece in piece_list:
    piece_queue.put(piece)


ip, port = announce(file_load)


for i in range(2):
    t = PeerConnection(piece_queue, ip, 51413)
    t.setDaemon(True)
    t.start()


piece_queue.join()


print "FILE FULLY DOWNLOADED (though not yet written)"





'''
class Peer(Protocol):
    def __init__(self, address):
        self.write(handshake?)
    def dataReceived(self, data):
        self.data += data
        # bunch of if statements

class PeerFactory():
    def buildProtocol(address):
        Peer(address)

if __name__ == '__main__':
    fac = PeerFactory()
    for peer in peerList
        fac.buildProtocol(peer)

'''

