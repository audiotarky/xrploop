import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from random import randint, seed
from uuid import uuid4

from flask import (
    Flask,
    render_template,
    jsonify,
    url_for,
    redirect,
    request,
    session,
    make_response,
)

from flask_sock import Sock
from functools import cache
from requests.exceptions import HTTPError
from xrpl.account import get_balance
from xrpl.clients import WebsocketClient
from xrpl.models.requests import (
    AccountChannels,
    AccountTx,
    ChannelAuthorize,
)
from xrpl.models.transactions import (
    Memo,
    PaymentChannelClaim,
    PaymentChannelCreate,
)
from xrpl.transaction import (
    get_transaction_from_hash,
    safe_sign_and_autofill_transaction,
    safe_sign_and_submit_transaction,
)
from xrpl.utils import (
    datetime_to_ripple_time,
    drops_to_xrp,
    hex_to_str,
    ripple_time_to_datetime,
    str_to_hex,
    xrp_to_drops,
)
from xrpl.wallet import Wallet
from xumm import XummSdk
from authlib.integrations.flask_client import OAuth

testnet_wss = "wss://s.altnet.rippletest.net:51233/"

with Path("creds.json").open() as f:
    creds = json.load(f)
    xumm_sdk = XummSdk(creds["x-api-key"], creds["x-api-secret"])
    target_creds = creds["server_creds"]
    source_creds = creds["source_creds"]

destination = Wallet(target_creds["secret"], target_creds["seq_number"])

xrpl_client = WebsocketClient(testnet_wss)


app = Flask(__name__)
app.secret_key = str(uuid4())
app.config["SESSION_TYPE"] = "filesystem"
oauth = OAuth(app)
oauth_base_url = "https://oauth2.xumm.app/"
from xumm import api_key as XUMM_CLIENT_ID, api_secret as XUMM_CLIENT_SECRET

CONF_URL = "https://oauth2.xumm.app/.well-known/openid-configuration"
remote = oauth.register(
    name="XUMM",
    server_metadata_url=CONF_URL,
    client_id=XUMM_CLIENT_ID,
    client_secret=XUMM_CLIENT_SECRET,
)
sock = Sock(app)


def xrp_str_balance(wallet):
    xrpl_client.open()
    if type(wallet) == Wallet:
        return (
            f"{drops_to_xrp(str(get_balance(wallet.classic_address, xrpl_client))):.2f}"
        )

    return f"{drops_to_xrp(str(get_balance(wallet, xrpl_client))):.2f}"


def create_channel_socket(submitter, destination_tag=None):
    then = datetime.now() + timedelta(days=28)
    xrpl_client.open()
    create_channel = PaymentChannelCreate(
        account=submitter,
        destination=target_creds["address"],
        destination_tag=destination_tag,
        amount=xrp_to_drops(30),
        cancel_after=datetime_to_ripple_time(then),
        public_key=destination.public_key,
        settle_delay=5,
    )

    try:
        payload = xumm_sdk.payload.create(create_channel.to_xrpl())

        return payload
    except HTTPError as he:
        print(he.response.text)
    except Exception as e:
        print(e)


def get_channels(source_address, destination, xrpl_client):
    xrpl_client.open()
    channels_request = AccountChannels(
        account=source_address,
        destination_account=destination.classic_address,
    )

    return xrpl_client.request(channels_request)


def close_channel(channel):
    app.logger.info(f"Closing {channel} - Not implemented yet")


def path_to_int(path):
    seed(path)
    return randint(0, 10000000)


def get_signature(claim_part):
    """
    This needs to not call the server...
    """
    channel_auth = ChannelAuthorize(**claim_part, secret=destination.seed)
    result = xrpl_client.request(channel_auth)
    return result.result["signature"]


def submit(txn, wallet):
    result = safe_sign_and_submit_transaction(txn, wallet, xrpl_client)
    if not result.is_successful():
        app.logger.warn("transaction wasn't submitted")
    elif result.result["engine_result_code"] != 0:
        app.logger.warn(
            f'{result.result["engine_result"]}: {result.result["engine_result_message"]}'
        )
    return result


def make_claim(channel_id, total_amount, url):
    claim_part = {
        "amount": xrp_to_drops(total_amount),
        "channel_id": channel_id,
    }
    signature = get_signature(claim_part)

    unsigned_pay_up = PaymentChannelClaim(
        account=destination.classic_address,
        channel=channel_id,
        amount=claim_part["amount"],
        balance=claim_part["amount"],
        memos=[Memo.from_dict({"memo_data": str_to_hex(url)})],
        public_key=destination.public_key,
        signature=signature,
    )

    signed_pay_up = safe_sign_and_autofill_transaction(
        unsigned_pay_up, destination, xrpl_client
    )

    return submit(signed_pay_up, destination)


@app.route("/login")
@app.route("/login/")
def login():
    redirect_uri = url_for("authorize", _external=True)
    return remote.authorize_redirect(redirect_uri)


@app.route("/authorize")
@app.route("/authorize/")
def authorize():
    token = remote.authorize_access_token()
    # you can save the token into database
    profile = remote.get("https://oauth2.xumm.app/userinfo", token=token).json()
    session["info"] = {
        "expires": token["expires_at"],
        "wallet_address": profile["sub"],
        "proSubscription": profile["proSubscription"],
        "avatar": profile["picture"],
        "email": profile["email"],
    }

    response = make_response(redirect(url_for("index")))
    response.set_cookie("wallet_address", session["info"]["wallet_address"])
    return response


@cache
@app.route("/transactions")
def get_transactions(**kwargs):
    marker = kwargs
    info = defaultdict(Counter)
    xrpl_client.open()
    if marker:
        account_transactions = AccountTx(
            account=destination.classic_address, marker=marker
        )
    else:
        account_transactions = AccountTx(
            account=destination.classic_address,
            ledger_index_min=-1,
            ledger_index_max=-1,
        )
    response = xrpl_client.request(account_transactions)

    marker = response.result.get("marker", {})
    for txn in response.result["transactions"]:
        info["totals"]["transactions"] += 1
        t = txn["tx"]

        if "date" in t:
            t["date"] = ripple_time_to_datetime(t["date"]).isoformat()
        loop_dest = ""
        for m in t.get("Memos", []):
            # TODO: need to have these be namespaced somehow
            loop_dest = hex_to_str(m["Memo"]["MemoData"])
            m["Memo"]["MemoData"] = loop_dest

        if t.get("TransactionType", None) == "PaymentChannelClaim":
            details = get_transaction_from_hash(t["hash"], xrpl_client).result
            t["TransactionResult"] = details["meta"]["TransactionResult"]
            info[loop_dest][t["TransactionResult"]] += 1
    if marker:
        for k, v in get_transactions(**marker).items():
            info[k] += v
    return jsonify(info)


@sock.route("/record")
def record(sock):
    while True:
        xrpl_client.open()
        data = json.loads(sock.receive())

        result = make_claim(data["channel"], data["total"], data["url"])

        result_dict = result.to_dict()

        if result_dict["result"]["engine_result_code"] != 0:
            app.logger.debug(result_dict["result"]["tx_json"])

        balances = {
            "destination": xrp_str_balance(destination),
            "source": xrp_str_balance(session["info"]["wallet_address"]),
            "data": data,
            "claim_result": {
                "engine_result": result_dict["result"]["engine_result"],
                "engine_result_message": result_dict["result"]["engine_result_message"],
                "txn": result_dict["result"]["tx_json"],
            },
        }

        sock.send(json.dumps(balances))


@app.route("/<path>")
@app.route("/")
def index(path=0):
    xrpl_client.open()
    source = session.get("info", {}).get("wallet_address", None)
    if not source:
        source = request.cookies.get("wallet_address", None)
        session["info"] = {"wallet_address": source}
    channel_list = []
    balances = {"destination": xrp_str_balance(destination)}
    active_channel = None
    xumm_socket = None
    if source:
        balances["source"] = xrp_str_balance(source)
        channels = get_channels(source, destination, xrpl_client)
        channel_list = []
        xumm_socket = create_channel_socket(source)
        for c in channels.result["channels"]:
            if c["amount"] == c["balance"]:
                close_channel(c)

            channel_list.append(c)
        channel_list = sorted(channel_list, key=lambda x: x["balance"], reverse=True)
        channel_list = sorted(
            channel_list, key=lambda x: x["cancel_after"], reverse=True
        )
        app.logger.info(channel_list)
        if len(channel_list):
            active_channel = channel_list[0]
        else:
            active_channel = None
    response = make_response(
        render_template(
            "index.html",
            balances=balances,
            channels=channel_list[:5],
            active_channel=active_channel,
            xumm_socket=xumm_socket,
            ripple_time_to_datetime=ripple_time_to_datetime,
            drops_to_xrp=drops_to_xrp,
        )
    )
    if xumm_socket:
        app.logger.debug(xumm_socket.refs)
        response.set_cookie("xumm_socket", xumm_socket.refs.websocket_status)
        response.set_cookie("xumm_png", xumm_socket.refs.qr_png)
        response.set_cookie("xumm_next", xumm_socket.next.always)
        response.set_cookie("activeChannel", active_channel["channel_id"])
    return response


if __name__ == "__main__":
    app.run(debug=True, ssl_context="adhoc")
