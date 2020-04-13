#!/usr/local/bin/python

import argparse
import json
import logging
import os
import requests
import sys

field_map = (
    (lambda x: x["image_path"], "4"),
    (lambda x: x["access_ports"], "7"),
    (lambda x: x["default_flavor"]["name"], "9"),
)

def get_logger():
    class GithubActionFormatter(logging.Formatter):
        def format(self, rec):
            if rec.levelname in ("DEBUG", "WARNING", "ERROR"):
                msg = f"::{rec.levelname.lower()} " \
                      f"file={rec.filename},line={rec.lineno}::{rec.msg}"
                return msg.replace("\n", "|")
            else:
                return super(GithubActionFormatter, self).format(rec)

    logger = logging.getLogger(__file__)
    ch = logging.StreamHandler()
    formatter = GithubActionFormatter("[%(levelname)s] %(message)s")
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    if os.getenv("ACTIONS_STEP_DEBUG") == "true":
        logger.setLevel(logging.DEBUG)

    return logger

def die(msg, rc=2):
    print(f"::error::{msg}")
    sys.exit(rc)

def set_output(name, value):
    print(f"::set-output name={name}::{value}")

def get_image_revision():
    ref = os.getenv('GITHUB_REF')
    if ref == "refs/heads/master":
        return "latest"
    elif ref.startswith("refs/tags/"):
        return ref.split("/")[-1]
    else:
        tokens = ref.split("/")
        imagerev = "-".join(tokens[2:])
        if tokens[1] == "pull":
            imagerev = "pr-" + imagerev
        return imagerev

def app_diff(oldapp, newapp):
    fields = []
    for (field, field_id) in field_map:
        if field(oldapp) != field(newapp):
            fields.append(field_id)

    return fields

def load_response(r, stream=False):
    items = r.text.splitlines() if stream else [ r.text ]
    resp = []
    for item in items:
        d = json.loads(item)
        if len(d) == 1 and "data" in d:
            d = d["data"]
        resp.append(d)
    return resp if stream else resp[0]

def get_mc(console, username, password):
    r = requests.post(f"{console}/api/v1/login",
                      json={"username": username, "password": password})
    if r.status_code != requests.codes.ok:
        logger.critical(f"MC login failed: {console}: {r.status_code} {r.text}")
        die(f"Failed to log in to the console: {console}")

    token = r.json()["token"]
    apibase = f"{console}/api/v1/auth"

    def mc(path, method="POST", headers={}, data={},
           success_codes=[requests.codes.ok], **kwargs):
        req_hdrs = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        req_hdrs.update(headers)
        if data:
            req_data = data
        else:
            req_data = kwargs

        r = requests.request(method, f"{apibase}/{path}",
                             headers=req_hdrs,
                             json=req_data)
        if r.status_code not in success_codes:
            logger.critical(f"MC call failed: {console} {path}: {r.status_code} {r.text}")
            die(f"MC call failed: {path}, {r.status_code}")

        try:
            resp = load_response(r)
        except Exception:
            # Check if response is a JSON stream
            resp = load_response(r, stream=True)

        return resp

    return mc

def check_status(resp):
    success = True
    if isinstance(resp, list):
        for item in resp:
            if "message" in item:
                logger.debug(item["message"])
            if "result" in item:
                code = int(item["result"].get("code"))
                if code != requests.codes.ok:
                    logger.error(item["result"].get("message") or f"Error: {code}")
                    success = False
                else:
                    logger.debug(item["result"].get("message"))
    return success

logger = get_logger()

def main(args):
    actions = []
    for envvar in ("INPUT_USERNAME", "INPUT_PASSWORD"):
        if not os.getenv(envvar):
            die(f"Mandatory variable not set: {envvar}")

    imagerev = get_image_revision()
    image = f"{args.imagepath}:{imagerev}"
    set_output("image", image)
    set_output("setup", args.setup)

    if args.setup == "main":
        console = "https://console.mobiledgex.net"
    else:
        console = f"https://console-{args.setup}.mobiledgex.net"

    mc = get_mc(console, username=os.getenv("INPUT_USERNAME"),
		password=os.getenv("INPUT_PASSWORD"))

    # Get App
    appkey = {
        "name": args.appname,
        "organization": args.apporg,
        "version": args.appvers,
    }
    logger.debug(f"App key = {appkey}")

    data = {
        "region": args.region,
        "app": {
            "key": appkey,
            "image_path": image,
            "image_type": 1,
            "access_ports": args.accessports,
            "default_flavor": {
                "name": args.flavor
            }
        }
    }
    logger.debug(f"App data = {data}")

    # Check if app exists
    app = mc("ctrl/ShowApp", data={
        "region": args.region,
        "app": { "key": appkey },
    })

    if app:
        logger.info(f"Updating existing app: {appkey}")
        action = "UpdateApp"
        data["app"]["fields"] = app_diff(app, data["app"])
    else:
        logger.info(f"Creating new app: {appkey}")
        action = "CreateApp"

    # Create/update app
    actions.append(action)
    mc(f"ctrl/{action}", data=data)

    for clustertuple in args.clustertuple.split(","):
        tokens = clustertuple.split(":")
        cloudletname = tokens.pop(0)
        cloudletorg = tokens.pop(0)
        clustername = tokens.pop(0) if tokens else "autocluster"
        clusterorg = tokens.pop(0) if tokens else args.apporg

        appinst = mc("ctrl/ShowAppInst", data={
            "region": args.region,
            "appinst": {
            },
        })

        logger.debug(f"Creating app in {clustername},{clusterorg} @ {cloudletname},{cloudletorg}")
        data={
            "region": args.region,
            "appinst": {
                "key": {
                    "app_key": appkey,
                    "cluster_inst_key": {
                        "cloudlet_key": {
                            "name": cloudletname,
                            "organization": cloudletorg,
                        },
                        "cluster_key": {
                            "name": clustername,
                        },
                        "organization": clusterorg,
                    },
                },
            },
        }

        appinst = mc("ctrl/ShowAppInst", data=data)
        if appinst:
            logger.info(f"Updating app instance {clustername},{clusterorg} @ {cloudletname},{cloudletorg}")
            resp = mc("ctrl/RefreshAppInst", data=data)
            if check_status(resp):
                logger.debug(f"Updated app inst {clustername},{clusterorg} @ {cloudletname},{cloudletorg}")
        else:
            logger.info(f"Creating new app instance {clustername},{clusterorg} @ {cloudletname},{cloudletorg}")
            resp = mc("ctrl/CreateAppInst", data=data)
            if check_status(resp):
                logger.debug(f"Created app inst {clustername},{clusterorg} @ {cloudletname},{cloudletorg}")

    set_output("actions", ",".join(actions))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("appname", help="Name of the app")
    parser.add_argument("appvers", help="Version of the app")
    parser.add_argument("apporg", help="Organization the app belongs to")
    parser.add_argument("region", help="Region to deploy to")
    parser.add_argument("imagepath", help="Docker image path")
    parser.add_argument("accessports", help="Access ports")
    parser.add_argument("flavor", help="Flavor")
    parser.add_argument("--clustertuple", help="List of clusters/cloudlets to deploy app to")
    parser.add_argument("--setup", "-s", help="Setup to deploy app to",
                        default="main")
    args = parser.parse_args()

    main(args)
