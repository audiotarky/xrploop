let stop = false;

function str_obj(str) {
    str = str.split('; ');
    var result = {};
    for (var i = 0; i < str.length; i++) {
        var cur = str[i].split('=');
        result[cur[0]] = cur[1];
    }
    return result;
}

allCookies = str_obj(document.cookie);

if (allCookies.wallet_address) {
    document.getElementById('loginButton').remove();
}
const log = (text, color) => {
    document.getElementById('log').innerHTML += `<code style="color: ${color}">${text}</code><br>`;
};

const socket = new WebSocket('wss://' + location.host + '/record');

socket.addEventListener('message', ev => {
    data = JSON.parse(ev.data)
    log('>>> ' + JSON.stringify(data, null, 2), 'blue');
    console.log(data);
    if (data['claim_result']["engine_result"] === "tecUNFUNDED_PAYMENT") {
        console.log('Showing QR & stopping')
        showQR();
        stopWS();
    }
});

let activeChannel = allCookies.activeChannel || null;
let total = 0;

let timeoutID = null;

function stopWS() {
    clearTimeout(timeoutID);
    socket.close();
    stop = true;
}

function showQR() {
    if (allCookies.xumm_next && allCookies.xumm_png) {
        document.getElementById('info').innerHTML = `<h1 class="text-xl">Create Payment Channel</h1>`;
        document.getElementById('info').innerHTML += `<a href="${allCookies.xumm_next}"><img src="${allCookies.xumm_png}" /></a>`;
    }
}


function payMe(timeout = 5000) {
    console.log('Submit payment notice')
    payData = {
        url: document.location['pathname'],
        total: total,
        channel: activeChannel
    }
    if (activeChannel) {
        if (socket.readyState == socket.OPEN) {
            socket.send(JSON.stringify(payData));
        }
        total += 0.01;
        if (!stop) {
            timeoutID = setTimeout(payMe, timeout);
        }
    }
}

console.log(activeChannel)

if (activeChannel !== null) {
    payMe();
} else {
    console.log('Show QR to make new channel')
    showQR()
    xummSocket = new WebSocket(allCookies.xumm_socket);
    xummSocket.onmessage = function (event) {
        data = JSON.parse(event.data);
        console.log(data);
        if (data.payload_uuidv4 || false) {
            document.location.reload();
        }
    }
}