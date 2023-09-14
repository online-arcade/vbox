import websockets
import asyncio
import sys
import json
import argparse

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp

PIPELINE_DESC = '''
webrtcbin name=webrtc bundle-policy=max-bundle stun-server=stun://gamebox.zgwit.cn:3478
 v4l2src device=/dev/video0 ! videoconvert ! video/x-raw,format=I420,width=1280,height=720,framerate=10/1 ! queue ! vp8enc deadline=1 ! rtpvp8pay !
 queue ! application/x-rtp,media=video,encoding-name=VP8,payload=97 ! webrtc.
'''
SERVER_URL = 'ws://gamebox.zgwit.cn:8443'

from websockets.version import version as wsv

class WebRTCClient:
    def __init__(self, id_):
        self.id_ = id_
        self.conn = None
        self.pipe = None
        self.webrtc = None


    async def connect(self):
        self.conn = await websockets.connect(SERVER_URL)
        await self.conn.send('HELLO %s' % self.id_)
    
    def send_message(self, obj):
        msg = json.dumps(obj)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(msg))
        loop.close()

    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        print ('Sending offer:\n%s' % text)
        self.send_message({'sdp': {'type': 'offer', 'sdp': text}})

    def on_offer_created(self, promise, _, __):
        promise.wait()
        reply = promise.get_reply()
        #offer = reply['offer'] #structure error...
        offer = reply.get_value('offer')
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        print('on_negotiation_needed')
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def on_ice_candidate(self, _, mlineindex, candidate):
        print('on_ice_candidate', candidate)
        self.send_message({'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}})

    def start_pipeline(self):
        self.pipe = Gst.parse_launch(PIPELINE_DESC)
        self.webrtc = self.pipe.get_by_name('webrtc')

        #设置单向发送，但是没什么用
        #tran = self.webrtc.emit('get-transceiver', 0)
        #tran.direction = GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY
		
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.on_ice_candidate)
        self.pipe.set_state(Gst.State.PLAYING)

    def handle_sdp(self, message):
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
            print ('Received answer:\n%s' % sdp)
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
            promise = Gst.Promise.new()
            self.webrtc.emit('set-remote-description', answer, promise)
            promise.interrupt()
        elif 'ice' in msg:
            ice = msg['ice']
            candidate = ice['candidate']
            sdpmlineindex = ice['sdpMLineIndex']
            self.webrtc.emit('add-ice-candidate', sdpmlineindex, candidate)

    def close_pipeline(self):
        self.pipe.set_state(Gst.State.NULL)
        self.pipe = None
        self.webrtc = None

    async def loop(self):
        assert self.conn
        async for message in self.conn:
            print('[MSG]', message)
            if message == 'HELLO':
                print('HELLO')
            elif message == 'SESSION_OK': #不会发生
                print('SESSION_OK')
            elif message == 'OFFER_REQUEST':
                self.start_pipeline()
            elif message.startswith('ERROR'):
                print (message)
                self.close_pipeline()
                return 1
            else:
                self.handle_sdp(message)
        self.close_pipeline()
        return 0

    async def stop(self):
        if self.conn:
            await self.conn.close()
        self.conn = None


def check_plugins():
    needed = ["opus", "vpx", "nice", "webrtc", "dtls", "srtp", "rtp",
              "rtpmanager", "video4linux2"]
    missing = list(filter(lambda p: Gst.Registry.get().find_plugin(p) is None, needed))
    if len(missing):
        print('Missing gstreamer plugins:', missing)
        return False
    return True


if __name__=='__main__':
    Gst.init(None)
    if not check_plugins():
        sys.exit(1)
    parser = argparse.ArgumentParser()
    parser.add_argument('id', help='String ID of the peer')
    parser.add_argument('--server', help='Signalling server to connect to, eg "wss://127.0.0.1:8443"')
    args = parser.parse_args()
    c = WebRTCClient(args.id or "vbox")

    #一直运行
    while True:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(c.connect())
        res = loop.run_until_complete(c.loop())
        c.stop()
        print(res)