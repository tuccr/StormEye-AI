const video = document.getElementById("video");

async function start() {
  const pc = new RTCPeerConnection();
  pc.ontrack = event => {
    video.srcObject = event.streams[0];
  };

  // Add a transceiver in recvonly mode
  pc.addTransceiver("video", { direction: "recvonly" });

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // Send offer to the server
  const response = await fetch("/offer", {
    method: "POST",
    body: JSON.stringify(pc.localDescription),
    headers: { "Content-Type": "application/json" }
  });

  const answer = await response.json();
  await pc.setRemoteDescription(answer);
}

/*
 * TODO: Create listener here to release the VideoCapture on exit and make sure we can access the camera feed when we re-enter the webpage. May not need this but depends on approach taken in ../server.py
 */

start();
