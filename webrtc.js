var ws_server;
var ws_port;
var default_peer_id = "gst";
//var rtc_configuration = {iceServers: [{urls: "stun:stun.l.google.com:19302"}]};
var rtc_configuration = {iceServers: [{urls: "stun:gamebox.zgwit.cn:3478"}]};

var connect_attempts = 0;
var peer_connection = new RTCPeerConnection(rtc_configuration);

var ws_conn;

var callCreateTriggered = false;
var makingOffer = false;
var isSettingRemoteAnswerPending = false;


function resetState() {
    // This will call onServerClose()
    ws_conn.close();
}

function handleIncomingError(error) {
    console.error("ERROR: " + error);
    resetState();
}

function getVideoElement() {
    return document.getElementById("video");
}

function resetVideo() {
    document.getElementById("video").innerHTML = "";
}

function onIncomingSDP(sdp) {
	peer_connection.setRemoteDescription(sdp).then(() => {
		console.log("Remote SDP set");
		peer_connection.setLocalDescription().then(() => {
			let desc = peer_connection.localDescription;
			console.log("Got local description: ", JSON.stringify(desc));
			ws_conn.send(JSON.stringify({'sdp': desc}));
			if (peer_connection.iceConnectionState == "connected") {
				console.log("SDP " + desc.type + " sent, ICE connected, all looks OK");
			}
		});
	});
}


// ICE candidate received from peer, add it to the peer connection
function onIncomingICE(ice) {
    var candidate = new RTCIceCandidate(ice);
    peer_connection.addIceCandidate(candidate).catch(console.error);
}

function onConnectClicked() {
    var peer = document.getElementById("peer-connect").value
    ws_conn.send("SESSION "+peer)
}

function onServerMessage(event) {
    console.log("[MSG]", event.data);
    switch (event.data) {
        case "HELLO":
            console.log("Registered with server");
            //ws_conn.send("SESSION "+"vbox")
            return;
        case "SESSION_OK":
            ws_conn.send("OFFER_REQUEST");
            console.log("Sent OFFER_REQUEST, waiting for offer");
            return;
        default:
            if (event.data.startsWith("ERROR")) {
                handleIncomingError(event.data);
                return;
            }
            // Handle incoming JSON SDP and ICE messages
            try {
                msg = JSON.parse(event.data);
            } catch (e) {
                if (e instanceof SyntaxError) {
                    handleIncomingError("Error parsing incoming JSON: " + event.data);
                } else {
                    handleIncomingError("Unknown error parsing response: " + event.data);
                }
                return;
            }

            // Incoming JSON signals the beginning of a call
            if (!callCreateTriggered)
                createCall(msg);

            if (msg.sdp != null) {
                onIncomingSDP(msg.sdp);
            } else if (msg.ice != null) {
                onIncomingICE(msg.ice);
            } else {
                handleIncomingError("Unknown incoming JSON: " + msg);
            }
    }
}

function onServerClose(event) {
    console.log('Disconnected from server');
    resetVideo();

    if (peer_connection) {
        peer_connection.close();
        peer_connection = new RTCPeerConnection(rtc_configuration);
    }
    callCreateTriggered = false;

    // Reset after a second
    window.setTimeout(websocketServerConnect, 1000);
}

function onServerError(event) {
    console.error("Unable to connect to server, did you add an exception for the certificate?")
    // Retry after 3 seconds
    window.setTimeout(websocketServerConnect, 3000);
}


function websocketServerConnect() {
    connect_attempts++;
    if (connect_attempts > 3) {
        console.error("Too many connection attempts, aborting. Refresh page to try again");
        return;
    }
        
    // Fetch the peer id to use
    peer_id = Math.floor(Math.random() * (9000 - 10) + 10).toString();	
    var ws_url = 'ws://gamebox.zgwit.cn:8443'
    console.log("Connecting to server ", ws_url);
    ws_conn = new WebSocket(ws_url);
    /* When connected, immediately register with the server */
    ws_conn.addEventListener('open', (event) => {
        document.getElementById("peer-id").textContent = peer_id;
        ws_conn.send('HELLO ' + peer_id);
        console.log("Registering with server");
        // Reset connection attempts because we connected successfully
        connect_attempts = 0;
    });
    ws_conn.addEventListener('error', onServerError);
    ws_conn.addEventListener('message', onServerMessage);
    ws_conn.addEventListener('close', onServerClose);
}



function createCall() {
    callCreateTriggered = true;
    console.log('Configuring RTCPeerConnection');
    //peer_connection.ondatachannel = onDataChannel;

    peer_connection.ontrack = ({track, streams}) => {
        console.log("ontrack", track, streams);
        var videoElem = getVideoElement();

        videoElem.srcObject = streams[0];
		//videoElem.play();
    };

    peer_connection.onicecandidate = (event) => {
        console.log("onicecandidate", event);
        // We have a candidate, send it to the remote party with the
        // same uuid
        if (event.candidate == null) {
                console.log("ICE Candidate was null, done");
                return;
        }
        ws_conn.send(JSON.stringify({'ice': event.candidate}));
    };
    peer_connection.oniceconnectionstatechange = (event) => {
        console.log("oniceconnectionstatechange", event);
        if (peer_connection.iceConnectionState == "connected") {
            console.log("ICE gathering complete");
        }
    };

    // let the "negotiationneeded" event trigger offer generation
    peer_connection.onnegotiationneeded = async () => {
        console.log("onnegotiationneeded");
        console.log("Negotiation needed");
    };
}
